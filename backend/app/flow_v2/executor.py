from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.flow_v2.actions import RuntimeAction, SendMessageAction
from app.flow_v2.contracts import FlowV2EventType, FlowV2SessionStatus, RuntimeInput, RuntimeOutput
from app.flow_v2.event_store import FlowV2EventStore
from app.flow_v2.idempotency import FlowV2IdempotencyStore, resolve_event_kind, resolve_idempotency_key
from app.flow_v2.node_executors import NodeExecutorRegistry
from app.flow_v2.session_lock import FlowV2SessionLock
from app.flow_v2.session_manager import FlowV2SessionManager
from app.flow_v2.snapshot import FlowV2Snapshot, FlowV2SnapshotRepository
from app.flow_v2.transition_resolver import FlowV2TransitionError, TransitionResolver


class FlowV2ExecutionError(RuntimeError):
    pass


class FlowV2Executor:
    """The single Runtime V2 executor.

    It receives a published flow_version_id, loads exactly one immutable snapshot
    from flow_versions, appends events for every transition, and updates only the
    minimal session pointer needed to resume execution.
    """

    def __init__(
        self,
        *,
        snapshot_repository: FlowV2SnapshotRepository | None = None,
        event_store: FlowV2EventStore | None = None,
        session_manager: FlowV2SessionManager | None = None,
        transition_resolver: TransitionResolver | None = None,
        node_registry: NodeExecutorRegistry | None = None,
        idempotency_store: FlowV2IdempotencyStore | None = None,
        session_lock: FlowV2SessionLock | None = None,
    ) -> None:
        self.snapshot_repository = snapshot_repository or FlowV2SnapshotRepository()
        self.event_store = event_store or FlowV2EventStore()
        self.session_manager = session_manager or FlowV2SessionManager(self.event_store)
        self.transition_resolver = transition_resolver or TransitionResolver(self.event_store)
        self.node_registry = node_registry or NodeExecutorRegistry(
            event_store=self.event_store,
            transition_resolver=self.transition_resolver,
        )
        self.idempotency_store = idempotency_store or FlowV2IdempotencyStore()
        self.session_lock = session_lock or FlowV2SessionLock()

    def handle_input(self, db: Session, runtime_input: RuntimeInput) -> RuntimeOutput:
        snapshot = self.snapshot_repository.load(
            db,
            tenant_id=runtime_input.tenant_id,
            flow_version_id=runtime_input.flow_version_id,
        )
        session = self.session_manager.get_or_create(db, runtime_input=runtime_input, snapshot=snapshot)
        idempotency_metadata = {
            **runtime_input.metadata,
            "event_id": runtime_input.event_id or runtime_input.metadata.get("event_id"),
            "message_id": runtime_input.message_id or runtime_input.metadata.get("message_id"),
            "webhook_id": runtime_input.webhook_id or runtime_input.metadata.get("webhook_id"),
        }
        event_kind = resolve_event_kind(metadata=idempotency_metadata)
        idempotency_key = resolve_idempotency_key(input_message_id=runtime_input.input_message_id, metadata=idempotency_metadata)
        decision = self.idempotency_store.reserve_once(
            db,
            tenant_id=runtime_input.tenant_id,
            event_kind=event_kind,
            key=idempotency_key,
            session_id=session.id,
            metadata=idempotency_metadata,
        )
        if decision.is_duplicate:
            return RuntimeOutput(
                session_id=session.id,
                status=FlowV2SessionStatus(session.status),
                current_node_id=session.current_node_id,
                emitted_event_count=0,
            )

        with self.session_lock.acquire(db, tenant_id=runtime_input.tenant_id, session_id=session.id):
            emitted_before = session.last_event_index

            self.event_store.append(
                db,
                session=session,
                event_type=FlowV2EventType.INPUT_RECEIVED,
                payload={"text": runtime_input.message_text, "metadata": runtime_input.metadata},
                node_id=session.current_node_id,
                input_message_id=runtime_input.input_message_id or idempotency_key,
            )

            actions = self._execute_current_node(db, snapshot=snapshot, session=session, runtime_input=runtime_input)
            self.idempotency_store.mark_session(db, decision=decision, session_id=session.id)
            db.flush()
            return RuntimeOutput(
                session_id=session.id,
                status=FlowV2SessionStatus(session.status),
                current_node_id=session.current_node_id,
                effects=tuple(self._legacy_effect(action) for action in actions if self._legacy_effect(action) is not None),
                actions=tuple(actions),
                emitted_event_count=session.last_event_index - emitted_before,
            )

    def _execute_current_node(
        self, db: Session, *, snapshot: FlowV2Snapshot, session: Any, runtime_input: RuntimeInput
    ) -> list[RuntimeAction]:
        if not session.current_node_id:
            raise FlowV2ExecutionError("Session has no current node")
        node = snapshot.node_by_id.get(session.current_node_id)
        if node is None:
            raise FlowV2ExecutionError("Current node is absent from immutable snapshot")

        node_id = str(node["id"])
        self.event_store.append(db, session=session, event_type=FlowV2EventType.NODE_ENTERED, node_id=node_id)
        try:
            node_type = str(node.get("type") or self._node_data(node).get("type") or "message")
            result = self.node_registry.get(node_type).execute(
                db,
                snapshot=snapshot,
                session=session,
                node=node,
                runtime_input=runtime_input,
            )
            self.event_store.append(
                db,
                session=session,
                event_type=FlowV2EventType.NODE_EXECUTED,
                node_id=node_id,
                payload={"node_type": node_type, "status": result.status},
            )
            self.event_store.append(db, session=session, event_type=FlowV2EventType.NODE_COMPLETED, node_id=node_id)
        except FlowV2TransitionError:
            self.event_store.append(
                db,
                session=session,
                event_type=FlowV2EventType.NODE_EXECUTED,
                node_id=node_id,
                payload={"status": "transition_failed"},
            )
            self.event_store.append(db, session=session, event_type=FlowV2EventType.NODE_COMPLETED, node_id=node_id)
            self.event_store.append(db, session=session, event_type=FlowV2EventType.SESSION_FAILED, node_id=node_id)
            self.session_manager.move_to(db, session=session, node_id=node_id, status=FlowV2SessionStatus.FAILED)
            raise
        except RuntimeError:
            self.event_store.append(
                db,
                session=session,
                event_type=FlowV2EventType.NODE_EXECUTED,
                node_id=node_id,
                payload={"status": "failed"},
            )
            self.event_store.append(db, session=session, event_type=FlowV2EventType.NODE_COMPLETED, node_id=node_id)
            self.event_store.append(db, session=session, event_type=FlowV2EventType.SESSION_FAILED, node_id=node_id)
            self.session_manager.move_to(db, session=session, node_id=node_id, status=FlowV2SessionStatus.FAILED)
            raise

        if result.status == "scheduled":
            self.event_store.append(db, session=session, event_type=FlowV2EventType.SESSION_WAITING, node_id=result.next_node_id)
            self.session_manager.move_to(db, session=session, node_id=result.next_node_id, status=FlowV2SessionStatus.WAITING)
            return list(result.actions)
        if result.status == "wait":
            self.event_store.append(db, session=session, event_type=FlowV2EventType.SESSION_WAITING, node_id=node_id)
            self.session_manager.move_to(db, session=session, node_id=node_id, status=FlowV2SessionStatus.WAITING)
            return list(result.actions)

        self.event_store.append(
            db,
            session=session,
            event_type=FlowV2EventType.TRANSITION_SELECTED,
            node_id=node_id,
            payload={"target_node_id": result.next_node_id},
        )
        self.event_store.append(db, session=session, event_type=FlowV2EventType.SESSION_WAITING, node_id=result.next_node_id)
        self.session_manager.move_to(db, session=session, node_id=result.next_node_id, status=FlowV2SessionStatus.WAITING)
        return list(result.actions)

    @staticmethod
    def _legacy_effect(action: RuntimeAction) -> dict[str, Any] | None:
        if isinstance(action, SendMessageAction):
            return {"type": "send_message", "text": action.text}
        return None

    @staticmethod
    def _node_data(node: dict[str, Any]) -> dict[str, Any]:
        data = node.get("data")
        return data if isinstance(data, dict) else {}
