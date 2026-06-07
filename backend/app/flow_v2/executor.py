from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)


class FlowV2ExecutionError(RuntimeError):
    pass


MAX_RUNTIME_STEPS = 50


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
        logger.info(
            "[V2 SNAPSHOT] executor_loaded flow_version_id=%s tenant_id=%s start_node_id=%s nodes_count=%s edges_count=%s transitions_count=%s hash=%s",
            runtime_input.flow_version_id,
            runtime_input.tenant_id,
            snapshot.start_node_id,
            len(snapshot.nodes),
            len(snapshot.edges),
            len(snapshot.transitions),
            snapshot.hash,
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

            if self._is_delay_resumed(runtime_input):
                logger.info(
                    "[DELAY_RESUMED] executor_before_execute session_id=%s current_node_id=%s session_status=%s delay_job_id=%s",
                    session.id,
                    session.current_node_id,
                    session.status,
                    runtime_input.metadata.get("delay_job_id"),
                )

            actions = self._execute_current_node(db, snapshot=snapshot, session=session, runtime_input=runtime_input)
            self.idempotency_store.mark_session(db, decision=decision, session_id=session.id)
            db.flush()
            output = RuntimeOutput(
                session_id=session.id,
                status=FlowV2SessionStatus(session.status),
                current_node_id=session.current_node_id,
                effects=tuple(self._legacy_effect(action) for action in actions if self._legacy_effect(action) is not None),
                actions=tuple(actions),
                emitted_event_count=session.last_event_index - emitted_before,
            )
            if self._is_delay_resumed(runtime_input):
                logger.info(
                    "[DELAY_RESUMED] runtime_output session_id=%s status=%s current_node_id=%s runtime_output_actions_count=%s actions_empty=%s effects_count=%s emitted_event_count=%s",
                    output.session_id,
                    output.status,
                    output.current_node_id,
                    len(output.actions),
                    len(output.actions) == 0,
                    len(output.effects),
                    output.emitted_event_count,
                )
            return output

    def _execute_current_node(
        self, db: Session, *, snapshot: FlowV2Snapshot, session: Any, runtime_input: RuntimeInput
    ) -> list[RuntimeAction]:
        actions: list[RuntimeAction] = []

        for step in range(MAX_RUNTIME_STEPS):
            if not session.current_node_id:
                raise FlowV2ExecutionError("Session has no current node")
            node = snapshot.node_by_id.get(session.current_node_id)
            if node is None:
                raise FlowV2ExecutionError("Current node is absent from immutable snapshot")

            node_id = str(node["id"])
            self.event_store.append(db, session=session, event_type=FlowV2EventType.NODE_ENTERED, node_id=node_id)
            try:
                node_type = str(node.get("type") or self._node_data(node).get("type") or "message")
                logger.info(
                    "[V2 NODE EXECUTION] enter node_id=%s node_type=%s current_node_id=%s transitions_count=%s step=%s",
                    node_id,
                    node_type,
                    session.current_node_id,
                    len(snapshot.transitions),
                    step + 1,
                )
                logger.info(
                    "[EXECUTOR ENTER NODE] node_id=%s node_type=%s current_node_id=%s transitions_count=%s step=%s event_type=%s delay_resumed=%s reentered_delay_after_resume=%s target_final_node=%s",
                    node_id,
                    node_type,
                    session.current_node_id,
                    len(snapshot.transitions),
                    step + 1,
                    runtime_input.metadata.get("event_type"),
                    self._is_delay_resumed(runtime_input),
                    self._is_delay_resumed(runtime_input) and node_type == "delay",
                    node_id == "bccab03d-830a-4dc1-9e67-bcadf5666eee",
                )
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
            except FlowV2TransitionError as exc:
                logger.exception("[V2 NODE EXECUTION] transition_failed node_id=%s error=%s", node_id, exc)
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

            actions.extend(result.actions)

            if result.status == "scheduled":
                logger.info(
                    "[SESSION WAITING] node_id=%s node_type=%s waiting_node_id=%s reason=scheduled",
                    node_id,
                    node_type,
                    result.next_node_id,
                )
                self.event_store.append(db, session=session, event_type=FlowV2EventType.SESSION_WAITING, node_id=result.next_node_id)
                self.session_manager.move_to(db, session=session, node_id=result.next_node_id, status=FlowV2SessionStatus.WAITING)
                logger.info(
                    "[SESSION STATUS] node_id=%s node_type=%s current_node_id=%s session_status=%s reason=scheduled",
                    node_id,
                    node_type,
                    session.current_node_id,
                    session.status,
                )
                logger.info(
                    "[EXECUTOR STOP] node_id=%s node_type=%s current_node_id=%s session_status=%s reason=scheduled actions_count=%s",
                    node_id,
                    node_type,
                    session.current_node_id,
                    session.status,
                    len(actions),
                )
                return actions
            if result.status == "wait":
                waiting_node_id = result.next_node_id or node_id
                logger.info(
                    "[SESSION WAITING] node_id=%s node_type=%s waiting_node_id=%s reason=executor_result_wait actions_count=%s",
                    node_id,
                    node_type,
                    waiting_node_id,
                    len(result.actions),
                )
                self.event_store.append(db, session=session, event_type=FlowV2EventType.SESSION_WAITING, node_id=waiting_node_id)
                self.session_manager.move_to(db, session=session, node_id=waiting_node_id, status=FlowV2SessionStatus.WAITING)
                logger.info(
                    "[SESSION STATUS] node_id=%s node_type=%s current_node_id=%s session_status=%s reason=executor_result_wait",
                    node_id,
                    node_type,
                    session.current_node_id,
                    session.status,
                )
                logger.info(
                    "[EXECUTOR STOP] node_id=%s node_type=%s current_node_id=%s session_status=%s reason=executor_result_wait actions_count=%s",
                    node_id,
                    node_type,
                    session.current_node_id,
                    session.status,
                    len(actions),
                )
                return actions
            if result.status == "complete":
                self.event_store.append(db, session=session, event_type=FlowV2EventType.SESSION_COMPLETED, node_id=node_id)
                self.session_manager.move_to(db, session=session, node_id=None, status=FlowV2SessionStatus.COMPLETED)
                logger.info(
                    "[EXECUTOR STOP] node_id=%s node_type=%s current_node_id=%s session_status=%s reason=complete actions_count=%s",
                    node_id,
                    node_type,
                    session.current_node_id,
                    session.status,
                    len(actions),
                )
                return actions

            if not result.next_node_id:
                raise FlowV2ExecutionError(f"Node {node_id} continued without next_node_id")
            self.event_store.append(
                db,
                session=session,
                event_type=FlowV2EventType.TRANSITION_SELECTED,
                node_id=node_id,
                payload={"target_node_id": result.next_node_id},
            )
            self.session_manager.move_to(db, session=session, node_id=result.next_node_id, status=FlowV2SessionStatus.RUNNING)

        current_node_id = session.current_node_id
        self.event_store.append(
            db,
            session=session,
            event_type=FlowV2EventType.SESSION_FAILED,
            node_id=current_node_id,
            payload={"reason": "max_steps_exceeded", "max_steps": MAX_RUNTIME_STEPS},
        )
        self.session_manager.move_to(db, session=session, node_id=current_node_id, status=FlowV2SessionStatus.FAILED)
        raise FlowV2ExecutionError(f"Runtime V2 exceeded max_steps={MAX_RUNTIME_STEPS}")

    @staticmethod
    def _is_delay_resumed(runtime_input: RuntimeInput) -> bool:
        return runtime_input.metadata.get("event_type") == str(FlowV2EventType.DELAY_RESUMED)

    @staticmethod
    def _legacy_effect(action: RuntimeAction) -> dict[str, Any] | None:
        if isinstance(action, SendMessageAction):
            return {"type": "send_message", "text": action.text}
        return None

    @staticmethod
    def _node_data(node: dict[str, Any]) -> dict[str, Any]:
        data = node.get("data")
        return data if isinstance(data, dict) else {}
