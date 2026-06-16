from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Conversation, FlowVersion
from app.services.flow_analytics_service import track_flow_event

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
        if self._conversation_is_human(db, runtime_input=runtime_input):
            logger.info(
                "[V2 RUNTIME SKIPPED] reason=human_mode tenant_id=%s conversation_id=%s external_user_id=%s",
                runtime_input.tenant_id,
                runtime_input.conversation_id,
                runtime_input.external_user_id,
            )
            return RuntimeOutput(
                session_id=uuid.uuid4(),
                status=FlowV2SessionStatus.COMPLETED,
                current_node_id=None,
                emitted_event_count=0,
            )

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
        flow_id = self._flow_id_for_version(db, tenant_id=runtime_input.tenant_id, flow_version_id=runtime_input.flow_version_id)
        if str(getattr(session, "status", "")) == str(FlowV2SessionStatus.COMPLETED):
            logger.info(
                "[SESSION FINISHED] session_id=%s status=%s current_node_id=%s reason=ignore_future_message_auto_restart_disabled",
                session.id,
                session.status,
                session.current_node_id,
            )
            return RuntimeOutput(
                session_id=session.id,
                status=FlowV2SessionStatus.COMPLETED,
                current_node_id=session.current_node_id,
                emitted_event_count=0,
            )
        if getattr(session, "last_event_index", 0) == 0:
            self._track_analytics(db, session=session, flow_id=flow_id, event_type="flow_started", metadata={"external_user_id": runtime_input.external_user_id})
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
            self._track_analytics(db, session=session, flow_id=flow_id, event_type="message_received", node_id=session.current_node_id, event_key=runtime_input.message_text, metadata={"text": runtime_input.message_text})

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

    @staticmethod
    def _conversation_is_human(db: Session, *, runtime_input: RuntimeInput) -> bool:
        conversation = None
        if runtime_input.conversation_id and hasattr(db, "get"):
            conversation = db.get(Conversation, runtime_input.conversation_id)
        if conversation is None and hasattr(db, "execute"):
            external_user_id = str(runtime_input.external_user_id or "")
            phone = external_user_id.split(":", 1)[1] if ":" in external_user_id else external_user_id
            if phone:
                result = db.execute(
                    select(Conversation).where(
                        Conversation.tenant_id == runtime_input.tenant_id,
                        Conversation.phone_number == phone,
                    )
                ).scalars()
                conversation = result.first() if hasattr(result, "first") else None
        return str(getattr(conversation, "mode", "") or "").strip().lower() == "human"

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
            flow_id = self._flow_id_for_version(db, tenant_id=session.tenant_id, flow_version_id=session.flow_version_id)
            node_type = str(node.get("type") or self._node_data(node).get("type") or "message")
            self._track_analytics(db, session=session, flow_id=flow_id, event_type="node_entered", node_id=node_id, node_type=node_type, metadata={"node_label": self._node_data(node).get("label")})
            if self._node_data(node).get("is_conversion") is True:
                self._track_analytics(db, session=session, flow_id=flow_id, event_type="conversion_reached", node_id=node_id, node_type=node_type, event_key=str(self._node_data(node).get("conversion_label") or node_id), metadata={"conversion_label": self._node_data(node).get("conversion_label")})
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
                self._track_analytics(db, session=session, flow_id=flow_id, event_type="node_completed", node_id=node_id, node_type=node_type)
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
            for action in result.actions:
                if isinstance(action, SendMessageAction):
                    self._track_analytics(db, session=session, flow_id=flow_id, event_type="message_sent", node_id=node_id, node_type=node_type, metadata={"text": action.text})

            if self._is_terminal_node(node):
                logger.info(
                    "[SESSION FINISHED] node_id=%s node_type=%s reason=terminal_node_marked_end_flow actions_count=%s",
                    node_id,
                    node_type,
                    len(actions),
                )
                self.event_store.append(db, session=session, event_type=FlowV2EventType.SESSION_COMPLETED, node_id=node_id)
                self._track_analytics(db, session=session, flow_id=flow_id, event_type="flow_completed", node_id=node_id, node_type=node_type)
                self.session_manager.move_to(db, session=session, node_id=None, status=FlowV2SessionStatus.COMPLETED)
                return actions

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
                wait_reason = "ai_rag_wait_same_node" if node_type == "ai_rag" and waiting_node_id == node_id else "executor_result_wait"
                logger.info(
                    "[SESSION WAITING] node_id=%s node_type=%s waiting_node_id=%s reason=%s actions_count=%s",
                    node_id,
                    node_type,
                    waiting_node_id,
                    wait_reason,
                    len(result.actions),
                )
                if wait_reason == "ai_rag_wait_same_node":
                    logger.info(
                        "[FLOW SESSION TRANSITION] flow_id=%s session_id=%s node_id=%s from=ACTIVE to=WAITING reason=ai_rag_wait_same_node",
                        flow_id,
                        session.id,
                        node_id,
                    )
                self.event_store.append(db, session=session, event_type=FlowV2EventType.SESSION_WAITING, node_id=waiting_node_id)
                self.session_manager.move_to(db, session=session, node_id=waiting_node_id, status=FlowV2SessionStatus.WAITING)
                logger.info(
                    "[SESSION STATUS] node_id=%s node_type=%s current_node_id=%s session_status=%s reason=%s",
                    node_id,
                    node_type,
                    session.current_node_id,
                    session.status,
                    wait_reason,
                )
                logger.info(
                    "[EXECUTOR STOP] node_id=%s node_type=%s current_node_id=%s session_status=%s reason=%s actions_count=%s",
                    node_id,
                    node_type,
                    session.current_node_id,
                    session.status,
                    wait_reason,
                    len(actions),
                )
                return actions
            if result.status == "complete":
                self.event_store.append(db, session=session, event_type=FlowV2EventType.SESSION_COMPLETED, node_id=node_id)
                self._track_analytics(db, session=session, flow_id=flow_id, event_type="flow_completed", node_id=node_id, node_type=node_type)
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
            self._track_analytics(db, session=session, flow_id=flow_id, event_type="choice_selected", node_id=node_id, node_type=node_type, event_key=str(result.next_node_id), metadata={"target_node_id": result.next_node_id})
            self._track_analytics(db, session=session, flow_id=flow_id, event_type="transition_taken", node_id=node_id, node_type=node_type, event_key=str(result.next_node_id), metadata={"source_handle": "default", "target_node_id": result.next_node_id, "target_node_type": None})
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
    def _flow_id_for_version(db: Session, *, tenant_id: uuid.UUID, flow_version_id: uuid.UUID) -> uuid.UUID | None:
        try:
            row = db.query(FlowVersion.flow_id).filter(FlowVersion.id == flow_version_id, FlowVersion.tenant_id == tenant_id).first()
            return row[0] if row else None
        except Exception as exc:  # pragma: no cover
            logger.warning("event=flow_analytics_resolve_flow_failed flow_version_id=%s tenant_id=%s error=%s", flow_version_id, tenant_id, exc)
            return None

    @staticmethod
    def _track_analytics(db: Session, *, session: Any, flow_id: uuid.UUID | None, event_type: str, node_id: str | None = None, node_type: str | None = None, event_key: str | None = None, metadata: dict[str, Any] | None = None) -> None:
        if not flow_id:
            return
        try:
            track_flow_event(
                db,
                tenant_id=session.tenant_id,
                flow_id=flow_id,
                flow_version_id=session.flow_version_id,
                session_id=session.id,
                conversation_id=getattr(session, "conversation_id", None),
                contact_id=getattr(session, "contact_id", None),
                node_id=node_id,
                node_type=node_type,
                event_type=event_type,
                event_key=event_key,
                metadata=metadata or {},
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("event=flow_analytics_runtime_track_failed session_id=%s event_type=%s error=%s", getattr(session, "id", None), event_type, exc)

    @staticmethod
    def _is_delay_resumed(runtime_input: RuntimeInput) -> bool:
        return runtime_input.metadata.get("event_type") == str(FlowV2EventType.DELAY_RESUMED)

    @staticmethod
    def _is_terminal_node(node: dict[str, Any]) -> bool:
        data = FlowV2Executor._node_data(node)
        value = node.get("is_terminal", node.get("isTerminal", node.get("endFlow", data.get("is_terminal", data.get("isTerminal", data.get("endFlow"))))))
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "sim", "on"}
        return False

    @staticmethod
    def _legacy_effect(action: RuntimeAction) -> dict[str, Any] | None:
        if isinstance(action, SendMessageAction):
            return {"type": "send_message", "text": action.text}
        return None

    @staticmethod
    def _node_data(node: dict[str, Any]) -> dict[str, Any]:
        data = node.get("data")
        return data if isinstance(data, dict) else {}
