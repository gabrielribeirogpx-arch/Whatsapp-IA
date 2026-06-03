from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.flow_v2.contracts import FlowV2EventType, FlowV2SessionStatus, RuntimeInput, RuntimeOutput
from app.flow_v2.event_store import FlowV2EventStore
from app.flow_v2.node_executors import NodeExecutorRegistry
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
    ) -> None:
        self.snapshot_repository = snapshot_repository or FlowV2SnapshotRepository()
        self.event_store = event_store or FlowV2EventStore()
        self.session_manager = session_manager or FlowV2SessionManager(self.event_store)
        self.transition_resolver = transition_resolver or TransitionResolver(self.event_store)
        self.node_registry = node_registry or NodeExecutorRegistry(
            event_store=self.event_store,
            transition_resolver=self.transition_resolver,
        )

    def handle_input(self, db: Session, runtime_input: RuntimeInput) -> RuntimeOutput:
        snapshot = self.snapshot_repository.load(
            db,
            tenant_id=runtime_input.tenant_id,
            flow_version_id=runtime_input.flow_version_id,
        )
        session = self.session_manager.get_or_create(db, runtime_input=runtime_input, snapshot=snapshot)
        emitted_before = session.last_event_index

        self.event_store.append(
            db,
            session=session,
            event_type=FlowV2EventType.INPUT_RECEIVED,
            payload={"text": runtime_input.message_text, "metadata": runtime_input.metadata},
            node_id=session.current_node_id,
            input_message_id=runtime_input.input_message_id,
        )

        effects = self._execute_current_node(db, snapshot=snapshot, session=session, runtime_input=runtime_input)
        db.flush()
        return RuntimeOutput(
            session_id=session.id,
            status=FlowV2SessionStatus(session.status),
            current_node_id=session.current_node_id,
            effects=tuple(effects),
            emitted_event_count=session.last_event_index - emitted_before,
        )

    def _execute_current_node(
        self, db: Session, *, snapshot: FlowV2Snapshot, session: Any, runtime_input: RuntimeInput
    ) -> list[dict[str, Any]]:
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
            return list(result.effects)
        if result.status == "wait":
            self.event_store.append(db, session=session, event_type=FlowV2EventType.SESSION_WAITING, node_id=node_id)
            self.session_manager.move_to(db, session=session, node_id=node_id, status=FlowV2SessionStatus.WAITING)
            return list(result.effects)

        self.event_store.append(
            db,
            session=session,
            event_type=FlowV2EventType.TRANSITION_SELECTED,
            node_id=node_id,
            payload={"target_node_id": result.next_node_id},
        )
        self.event_store.append(db, session=session, event_type=FlowV2EventType.SESSION_WAITING, node_id=result.next_node_id)
        self.session_manager.move_to(db, session=session, node_id=result.next_node_id, status=FlowV2SessionStatus.WAITING)
        return list(result.effects)

    @staticmethod
    def _node_data(node: dict[str, Any]) -> dict[str, Any]:
        data = node.get("data")
        return data if isinstance(data, dict) else {}
