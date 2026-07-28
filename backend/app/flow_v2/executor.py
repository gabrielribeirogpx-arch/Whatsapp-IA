from __future__ import annotations

import logging
import uuid
from dataclasses import replace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Conversation, FlowVersion
from app.services.flow_analytics_service import track_flow_event

from app.flow_v2.actions import RuntimeAction, SendMessageAction
from app.flow_v2.contracts import FlowV2EventType, FlowV2SessionStatus, RuntimeInput, RuntimeOutput
from app.observability.runtime_choice_trace import runtime_exit, runtime_trace
from app.flow_v2.event_store import FlowV2EventStore
from app.flow_v2.idempotency import FlowV2IdempotencyStore, resolve_event_kind, resolve_idempotency_key
from app.flow_v2.node_executors import NodeExecutorRegistry
from app.flow_v2.session_lock import FlowV2SessionLock
from app.flow_v2.session_manager import FlowV2SessionManager
from app.flow_v2.snapshot import FlowV2Snapshot, FlowV2SnapshotRepository
from app.flow_v2.transition_resolver import FlowV2TransitionError, TransitionResolver
from app.services.execution_budget_service import ExecutionBudgetExceeded, get_or_create_budget, persist_budget

logger = logging.getLogger(__name__)


AI_SYSTEM_TERMINAL_INTERNAL_TYPES = {"ai_greeting", "ai_safe_fallback", "ai_calendar_agent"}
AI_SYSTEM_PENDING_CONTEXT_KEYS = {"pending_slot", "pending_confirmation", "pending_tool_action", "pending_slots", "partial_calendar_request", "pending_event", "pending_calendar_event", "partial_calendar_event", "pending_google_calendar_create_event"}


def _node_internal_type(node: dict[str, Any] | None) -> str:
    if not isinstance(node, dict):
        return ""
    data = FlowV2Executor._node_data(node)
    return str(data.get("ai_system_internal_type") or node.get("type") or data.get("type") or "").strip().lower()


def _is_ai_system_snapshot(snapshot: FlowV2Snapshot | None) -> bool:
    if snapshot is None:
        return False
    for node in snapshot.nodes:
        data = FlowV2Executor._node_data(node)
        if data.get("compiled_from_ai_system") or data.get("agent_system_template_id") or data.get("ai_system_internal_type"):
            return True
    return False


def _dispatcher_node_id(snapshot: FlowV2Snapshot | None) -> str | None:
    if snapshot is None:
        return None
    for node in snapshot.nodes:
        data = FlowV2Executor._node_data(node)
        if str(data.get("ai_system_internal_type") or "").strip().lower() == "ai_dispatcher":
            return str(node.get("id"))
    start = snapshot.node_by_id.get(str(snapshot.start_node_id or ""))
    if _node_internal_type(start) == "ai_dispatcher":
        return str(snapshot.start_node_id)
    return None


def _has_active_calendar_slot_filling(session: Any) -> bool:
    for container in (getattr(session, "variables", None), getattr(session, "context", None), getattr(session, "metadata", None)):
        if not isinstance(container, dict):
            continue
        if (
            container.get("conversation_state") == "calendar_slot_filling"
            and container.get("waiting_specialist") == "calendar"
            and isinstance(container.get("pending_slots"), list)
            and len(container.get("pending_slots") or []) > 0
        ):
            return True
    return False


def _has_pending_ai_system_context(session: Any) -> bool:
    if _has_active_calendar_slot_filling(session):
        return True
    containers = [
        getattr(session, "variables", None),
        getattr(session, "context", None),
        getattr(session, "metadata", None),
    ]
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in AI_SYSTEM_PENDING_CONTEXT_KEYS:
            if container.get(key):
                return True
    return False


def _is_user_text_message(message: Any) -> bool:
    text = str(getattr(message, "message_text", "") or "").strip()
    if not text:
        return False
    metadata = getattr(message, "metadata", None)
    if isinstance(metadata, dict):
        direction = str(metadata.get("direction") or metadata.get("message_direction") or "").strip().lower()
        if direction and direction not in {"inbound", "user", "incoming"}:
            return False
        message_type = str(metadata.get("message_type") or metadata.get("type") or "text").strip().lower()
        if message_type not in {"", "text", "conversation"}:
            return False
    return True


def should_restart_at_dispatcher_for_ai_system(session: Any, message: Any, snapshot: FlowV2Snapshot | None = None) -> bool:
    if not _is_ai_system_snapshot(snapshot):
        return False
    if not _is_user_text_message(message):
        return False
    if _has_active_calendar_slot_filling(session):
        return False
    if _has_pending_ai_system_context(session):
        return False
    current_node_id = str(getattr(session, "current_node_id", "") or "")
    node = snapshot.node_by_id.get(current_node_id) if snapshot is not None and current_node_id else None
    return _node_internal_type(node) in AI_SYSTEM_TERMINAL_INTERNAL_TYPES


class FlowV2ExecutionError(RuntimeError):
    pass


MAX_RUNTIME_STEPS = 50

# A provider reply belongs only to the Choice at which the session was waiting.
# One RuntimeInput may traverse several synchronous nodes, so these fields must
# not leak into a later Choice during the same execution.
CHOICE_REPLY_METADATA_KEYS = frozenset(
    {"selected_row_id", "interactive_reply_id", "row_id", "sourceHandle", "runtime_choice_key"}
)


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
        budget = get_or_create_budget(runtime_input.metadata, runtime_input.tenant_id)
        persist_budget(runtime_input.metadata, budget)
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
        session_node = snapshot.node_by_id.get(str(getattr(session, "current_node_id", "") or ""))
        session_node_type = str(
            (session_node or {}).get("type") or self._node_data(session_node or {}).get("type") or ""
        ).strip().lower()
        waiting_for_choice = (
            str(getattr(session, "status", "")) == str(FlowV2SessionStatus.WAITING)
            and session_node_type == "choice"
        )
        logger.info(
            "event=runtime_v2_choice_trace stage=session_loaded status=found reason=session_ready "
            "session_id=%s current_node_id=%s waiting_for_choice=%s session_status=%s node_type=%s runtime_choice_key=%s",
            getattr(session, "id", None),
            getattr(session, "current_node_id", None),
            waiting_for_choice,
            getattr(session, "status", None),
            session_node_type or None,
            runtime_input.metadata.get("runtime_choice_key"),
        )
        runtime_trace(logger, "RuntimeV2Executor.session_loaded", metadata=runtime_input.metadata,
                      correlation_id=runtime_input.input_message_id, conversation_id=runtime_input.conversation_id,
                      session_id=session.id, flow_id=getattr(snapshot, "flow_id", None), flow_version_id=runtime_input.flow_version_id,
                      current_node_id=session.current_node_id, waiting_for_choice=waiting_for_choice,
                      current_wait_node=session.current_node_id if waiting_for_choice else None)
        if runtime_input.metadata.get("runtime_choice_key") and not waiting_for_choice:
            logger.error(
                "event=runtime_v2_choice_trace stage=session_validation status=failed reason=waiting_for_choice_false "
                "session_id=%s current_node_id=%s waiting_for_choice=%s session_status=%s node_type=%s runtime_choice_key=%s",
                getattr(session, "id", None),
                getattr(session, "current_node_id", None),
                waiting_for_choice,
                getattr(session, "status", None),
                session_node_type or None,
                runtime_input.metadata.get("runtime_choice_key"),
            )
        self._bind_numeric_choice_if_waiting(snapshot=snapshot, session=session, runtime_input=runtime_input)
        if _is_ai_system_snapshot(snapshot):
            logger.info(
                "event=AI_SYSTEM_CONTINUOUS_ROUTING_DETECTED session_id=%s current_node_id=%s dispatcher_node_id=%s",
                getattr(session, "id", None),
                getattr(session, "current_node_id", None),
                _dispatcher_node_id(snapshot),
            )
        if should_restart_at_dispatcher_for_ai_system(session, runtime_input, snapshot):
            dispatcher_node_id = _dispatcher_node_id(snapshot)
            if dispatcher_node_id and dispatcher_node_id != getattr(session, "current_node_id", None):
                logger.info(
                    "event=AI_SYSTEM_RESUME_AT_DISPATCHER session_id=%s from_node_id=%s dispatcher_node_id=%s",
                    getattr(session, "id", None),
                    getattr(session, "current_node_id", None),
                    dispatcher_node_id,
                )
                self.session_manager.move_to(db, session=session, node_id=dispatcher_node_id, status=FlowV2SessionStatus.RUNNING)
        elif _is_ai_system_snapshot(snapshot) and _has_pending_ai_system_context(session):
            ctx = getattr(session, "context", None) if isinstance(getattr(session, "context", None), dict) else {}
            logger.info(
                "event=AI_SYSTEM_KEEP_SLOT_CONTEXT session_id=%s previous_node_id=%s waiting_specialist=%s pending_slots=%s partial_calendar_request=%s incoming_message=%s selected_node_id=%s",
                getattr(session, "id", None),
                getattr(session, "current_node_id", None),
                ctx.get("waiting_specialist"),
                ctx.get("pending_slots"),
                ctx.get("partial_calendar_request"),
                getattr(runtime_input, "message_text", None),
                getattr(session, "current_node_id", None),
            )
            if _has_active_calendar_slot_filling(session):
                logger.info(
                    "event=AI_SYSTEM_RESUME_SPECIALIST_DIRECTLY session_id=%s previous_node_id=%s waiting_specialist=%s pending_slots=%s partial_calendar_request=%s incoming_message=%s selected_node_id=%s",
                    getattr(session, "id", None), getattr(session, "current_node_id", None), ctx.get("waiting_specialist"), ctx.get("pending_slots"), ctx.get("partial_calendar_request"), getattr(runtime_input, "message_text", None), getattr(session, "current_node_id", None),
                )
        flow_id = self._flow_id_for_version(db, tenant_id=runtime_input.tenant_id, flow_version_id=runtime_input.flow_version_id)
        if str(getattr(session, "status", "")) == str(FlowV2SessionStatus.COMPLETED):
            runtime_exit(logger, "RuntimeV2Executor", reason="completed_session_auto_restart_disabled",
                         metadata=runtime_input.metadata, correlation_id=runtime_input.input_message_id,
                         conversation_id=runtime_input.conversation_id, session_id=session.id,
                         flow_id=flow_id, flow_version_id=runtime_input.flow_version_id,
                         current_node_id=session.current_node_id, waiting_for_choice=False)
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
            runtime_exit(logger, "RuntimeV2Executor", reason="duplicate_input", metadata=runtime_input.metadata,
                         correlation_id=runtime_input.input_message_id, conversation_id=runtime_input.conversation_id,
                         session_id=session.id, flow_id=flow_id, flow_version_id=runtime_input.flow_version_id,
                         current_node_id=session.current_node_id)
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
    def _result_keeps_terminal_node_waiting(*, node: dict[str, Any], node_type: str, result: Any) -> bool:
        if str(getattr(result, "status", "") or "") != "wait":
            return False
        data = FlowV2Executor._node_data(node)
        normalized_node_type = str(node_type or "").strip().lower()
        if normalized_node_type == "ai_agent":
            behavior = str(
                data.get("after_agent_behavior")
                or data.get("afterAgentBehavior")
                or data.get("after_answer_behavior")
                or data.get("afterAnswerBehavior")
                or ""
            ).strip().lower()
            return behavior == "wait_same_node" and (getattr(result, "next_node_id", None) in (None, str(node.get("id"))))
        if normalized_node_type == "ai_system":
            return getattr(result, "next_node_id", None) in (None, str(node.get("id")))
        if normalized_node_type in {"ai_rag", "ai_response"}:
            behavior = str(data.get("after_answer_behavior") or data.get("afterAnswerBehavior") or "").strip().lower()
            return behavior == "wait_same_node" and (getattr(result, "next_node_id", None) in (None, str(node.get("id"))))
        return False

    @staticmethod
    def _bind_numeric_choice_if_waiting(*, snapshot: FlowV2Snapshot, session: Any, runtime_input: RuntimeInput) -> None:
        current_node_id = str(getattr(session, "current_node_id", "") or "")
        node = snapshot.node_by_id.get(current_node_id) if current_node_id else None
        node_type = str((node or {}).get("type") or FlowV2Executor._node_data(node or {}).get("type") or "").strip().lower()
        if node_type not in {"condition", "choice"}:
            return
        metadata = runtime_input.metadata
        if metadata.get("row_id") or metadata.get("sourceHandle") or metadata.get("selected_row_id") or metadata.get("interactive_reply_id"):
            return
        normalized_choice = str(runtime_input.message_text or "").strip()
        if not normalized_choice.isdecimal():
            return
        metadata["row_id"] = normalized_choice
        metadata["sourceHandle"] = normalized_choice
        metadata["selected_row_id"] = normalized_choice
        metadata.setdefault("runtime_choice_key", normalized_choice)
        logger.info(
            "event=runtime_numeric_choice_detected message_text=%s normalized_choice=%s current_node_id=%s",
            runtime_input.message_text,
            normalized_choice,
            current_node_id,
        )

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
            runtime_trace(logger, "RuntimeV2Executor.step", metadata=runtime_input.metadata,
                          correlation_id=runtime_input.input_message_id, conversation_id=runtime_input.conversation_id,
                          session_id=session.id, flow_version_id=runtime_input.flow_version_id,
                          current_node_id=session.current_node_id, executor_step=step + 1, node_executed=False)
            if not session.current_node_id:
                logger.error(
                    "event=runtime_v2_choice_trace stage=executor status=failed reason=current_node_id_missing "
                    "session_id=%s current_node_id=%s runtime_choice_key=%s",
                    session.id, session.current_node_id, runtime_input.metadata.get("runtime_choice_key"),
                )
                raise FlowV2ExecutionError("Session has no current node")
            node = snapshot.node_by_id.get(session.current_node_id)
            if node is None:
                logger.error(
                    "event=runtime_v2_choice_trace stage=node_lookup status=failed reason=next_node_not_found "
                    "session_id=%s current_node_id=%s runtime_choice_key=%s",
                    session.id, session.current_node_id, runtime_input.metadata.get("runtime_choice_key"),
                )
                raise FlowV2ExecutionError("Current node is absent from immutable snapshot")

            node_id = str(node["id"])
            self.event_store.append(db, session=session, event_type=FlowV2EventType.NODE_ENTERED, node_id=node_id)
            flow_id = self._flow_id_for_version(db, tenant_id=session.tenant_id, flow_version_id=session.flow_version_id)
            node_type = str(node.get("type") or self._node_data(node).get("type") or "message")
            logger.info(
                "event=runtime_v2_choice_trace stage=node_entered status=success reason=executor_entered_node "
                "session_id=%s current_node_id=%s node_id=%s node_type=%s runtime_choice_key=%s step=%s",
                session.id, session.current_node_id, node_id, node_type,
                runtime_input.metadata.get("runtime_choice_key"), step + 1,
            )
            self._track_analytics(db, session=session, flow_id=flow_id, event_type="node_entered", node_id=node_id, node_type=node_type, metadata={"node_label": self._node_data(node).get("label")})
            if self._node_data(node).get("is_conversion") is True:
                self._track_analytics(db, session=session, flow_id=flow_id, event_type="conversion_reached", node_id=node_id, node_type=node_type, event_key=str(self._node_data(node).get("conversion_label") or node_id), metadata={"conversion_label": self._node_data(node).get("conversion_label")})
            try:
                budget = get_or_create_budget(runtime_input.metadata, session.tenant_id)
                budget.consume_runtime_step()
                persist_budget(runtime_input.metadata, budget)
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
            except ExecutionBudgetExceeded as exc:
                persist_budget(runtime_input.metadata, budget)
                logger.warning("[V2 BUDGET EXCEEDED] tenant_id=%s session_id=%s node_id=%s reason=%s", session.tenant_id, session.id, node_id, budget.exceeded_reason)
                self.event_store.append(db, session=session, event_type=FlowV2EventType.NODE_EXECUTED, node_id=node_id, payload={"status": "budget_exceeded", **budget.safe_metadata()})
                self.event_store.append(db, session=session, event_type=FlowV2EventType.NODE_COMPLETED, node_id=node_id)
                self.session_manager.move_to(db, session=session, node_id=node_id, status=FlowV2SessionStatus.COMPLETED)
                return actions
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
            except RuntimeError as exc:
                logger.exception(
                    "event=runtime_v2_choice_trace stage=node_execution status=failed reason=exception "
                    "session_id=%s node_id=%s node_type=%s runtime_choice_key=%s error_type=%s error=%s",
                    session.id, node_id, node_type, runtime_input.metadata.get("runtime_choice_key"),
                    type(exc).__name__, exc,
                )
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
            if node_type.strip().lower() == "choice" and result.status == "continue":
                runtime_input = self._without_choice_reply(runtime_input)
            for action in result.actions:
                if isinstance(action, SendMessageAction):
                    self._track_analytics(db, session=session, flow_id=flow_id, event_type="message_sent", node_id=node_id, node_type=node_type, metadata={"text": action.text})

            dispatcher_wait_node_id = self._ai_system_dispatcher_wait_node_id(snapshot=snapshot, session=session, node=node, result=result)
            if dispatcher_wait_node_id:
                logger.info(
                    "event=AI_SYSTEM_LAST_NODE_COMPLETED session_id=%s node_id=%s node_type=%s dispatcher_node_id=%s status=%s",
                    getattr(session, "id", None),
                    node_id,
                    node_type,
                    dispatcher_wait_node_id,
                    result.status,
                )
                self.event_store.append(db, session=session, event_type=FlowV2EventType.SESSION_WAITING, node_id=dispatcher_wait_node_id)
                self.session_manager.move_to(db, session=session, node_id=dispatcher_wait_node_id, status=FlowV2SessionStatus.WAITING)
                logger.info(
                    "event=AI_SYSTEM_SESSION_WAITING_AT_DISPATCHER session_id=%s current_node_id=%s waiting_node_id=%s",
                    getattr(session, "id", None),
                    getattr(session, "current_node_id", None),
                    dispatcher_wait_node_id,
                )
                return actions

            if self._is_terminal_node(node) and not self._result_keeps_terminal_node_waiting(node=node, node_type=node_type, result=result):
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
                logger.error(
                    "event=runtime_v2_choice_trace stage=executor status=failed reason=continued_without_next_node "
                    "session_id=%s node_id=%s node_type=%s runtime_choice_key=%s",
                    session.id, node_id, node_type, runtime_input.metadata.get("runtime_choice_key"),
                )
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
            logger.info(
                "event=runtime_v2_choice_trace stage=next_node_selected status=success reason=session_pointer_advanced "
                "session_id=%s from_node_id=%s next_node_id=%s next_node_exists=%s runtime_choice_key=%s",
                session.id, node_id, result.next_node_id, result.next_node_id in snapshot.node_by_id,
                runtime_input.metadata.get("runtime_choice_key"),
            )
            runtime_trace(logger, "next_node_execution", metadata=runtime_input.metadata,
                          correlation_id=runtime_input.input_message_id, conversation_id=runtime_input.conversation_id,
                          session_id=session.id, flow_version_id=runtime_input.flow_version_id,
                          current_node_id=node_id, next_node_id=result.next_node_id,
                          executor_step=step + 1, transition_found=True, node_executed=True)

        current_node_id = session.current_node_id
        self.event_store.append(
            db,
            session=session,
            event_type=FlowV2EventType.SESSION_FAILED,
            node_id=current_node_id,
            payload={"reason": "max_steps_exceeded", "max_steps": MAX_RUNTIME_STEPS},
        )
        self.session_manager.move_to(db, session=session, node_id=current_node_id, status=FlowV2SessionStatus.FAILED)
        logger.error(
            "event=runtime_v2_choice_trace stage=executor status=failed reason=executor_interrupted_max_steps "
            "session_id=%s current_node_id=%s max_steps=%s runtime_choice_key=%s",
            session.id, current_node_id, MAX_RUNTIME_STEPS, runtime_input.metadata.get("runtime_choice_key"),
        )
        raise FlowV2ExecutionError(f"Runtime V2 exceeded max_steps={MAX_RUNTIME_STEPS}")

    @staticmethod
    def _without_choice_reply(runtime_input: RuntimeInput) -> RuntimeInput:
        """Prevent one inbound selection from resolving multiple Choice nodes."""
        consumed_keys = [key for key in CHOICE_REPLY_METADATA_KEYS if key in runtime_input.metadata]
        if consumed_keys:
            logger.info(
                "event=runtime_v2_choice_reply_consumed metadata_keys=%s",
                sorted(consumed_keys),
            )
        metadata = {
            key: value
            for key, value in runtime_input.metadata.items()
            if key not in CHOICE_REPLY_METADATA_KEYS
        }
        return replace(runtime_input, metadata=metadata)


    @staticmethod
    def _ai_system_dispatcher_wait_node_id(*, snapshot: FlowV2Snapshot, session: Any, node: dict[str, Any], result: Any) -> str | None:
        if not _is_ai_system_snapshot(snapshot):
            return None
        if str(getattr(result, "status", "") or "") != "complete":
            return None
        if _has_pending_ai_system_context(session):
            logger.info(
                "event=AI_SYSTEM_KEEP_SLOT_CONTEXT session_id=%s current_node_id=%s",
                getattr(session, "id", None),
                getattr(session, "current_node_id", None),
            )
            return None
        if _node_internal_type(node) not in AI_SYSTEM_TERMINAL_INTERNAL_TYPES:
            return None
        dispatcher_node_id = _dispatcher_node_id(snapshot)
        if not dispatcher_node_id:
            return None
        return dispatcher_node_id

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
        value = node.get(
            "is_terminal",
            node.get(
                "isTerminal",
                node.get(
                    "endFlow",
                    node.get(
                        "end",
                        node.get(
                            "isEnd",
                            node.get(
                                "terminal",
                                data.get(
                                    "is_terminal",
                                    data.get(
                                        "isTerminal",
                                        data.get("endFlow", data.get("end", data.get("isEnd", data.get("terminal")))),
                                    ),
                                ),
                            ),
                        ),
                    ),
                ),
            ),
        )
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
