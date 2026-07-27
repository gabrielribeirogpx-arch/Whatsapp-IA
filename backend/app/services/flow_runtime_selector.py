from __future__ import annotations

import logging
import unicodedata
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.flow_v2.channel_adapter import WhatsAppAdapter
from app.flow_v2.contracts import resolve_runtime_choice_key
from app.flow_v2.runtime_worker import FlowV2InputEvent, FlowV2RuntimeWorker, FlowV2WorkerResult
from app.models import Conversation
from app.models.flow import Flow
from app.services.queue import enqueue_send_message
from app.services.flow_activation_service import MULTIPLE_ACTIVE_FLOWS_LOG

logger = logging.getLogger(__name__)

FLOW_RUNTIME_SELECTOR = "flow.runtime"
FLOW_RUNTIME_V1 = "v1"
FLOW_RUNTIME_V2 = "v2"
SUPPORTED_FLOW_RUNTIMES = {FLOW_RUNTIME_V1, FLOW_RUNTIME_V2}
RESTART_KEYWORDS = {"oi", "ola", "menu", "iniciar", "comecar", "start"}


@dataclass(frozen=True)
class FlowRuntimeDispatchResult:
    runtime: str
    processed_by_v2: bool = False
    worker_result: FlowV2WorkerResult | None = None
    automation_skipped: bool = False

    @property
    def should_run_v1(self) -> bool:
        return self.runtime == FLOW_RUNTIME_V1 and not self.processed_by_v2 and not self.automation_skipped


def normalize_restart_keyword(message_text: str | None) -> str:
    text = str(message_text or "").strip().lower()
    text = "".join(
        char for char in unicodedata.normalize("NFKD", text) if not unicodedata.combining(char)
    )
    return " ".join(text.split())


def is_restart_keyword(message_text: str | None) -> bool:
    return normalize_restart_keyword(message_text) in RESTART_KEYWORDS


def resolve_flow_runtime(flow: Flow | None) -> str:
    """Return the runtime for a flow, keeping legacy/missing values on V1."""

    runtime = str(getattr(flow, "runtime", "") or "").strip().lower()
    if runtime == FLOW_RUNTIME_V2:
        return FLOW_RUNTIME_V2
    return FLOW_RUNTIME_V1


def is_conversation_human(conversation: Conversation | None) -> bool:
    """Return True when automation must stay disabled for human service."""

    return str(getattr(conversation, "mode", "") or "").strip().lower() == "human"


def resolve_runtime_flow_for_conversation(
    *,
    db: Session,
    tenant_id: UUID,
    conversation: Conversation,
    message_text: str,
    is_interactive_reply: bool = False,
) -> Flow | None:
    """Find the flow whose runtime should handle this inbound WhatsApp message."""

    if is_conversation_human(conversation):
        logger.info(
            "[FLOW RUNTIME SKIPPED] reason=human_mode tenant_id=%s conversation_id=%s",
            tenant_id,
            getattr(conversation, "id", None),
        )
        return None

    restart_requested = not is_interactive_reply and is_restart_keyword(message_text)
    if restart_requested:
        logger.info(
            "event=flow_restart_keyword_detected tenant_id=%s conversation_id=%s reason=restart_keyword",
            tenant_id,
            getattr(conversation, "id", None),
        )

    current_flow_id = getattr(conversation, "current_flow_id", None) or getattr(conversation, "current_flow", None)
    if current_flow_id and not restart_requested:
        current_flow = db.execute(
            select(Flow).where(
                Flow.id == current_flow_id,
                Flow.tenant_id == tenant_id,
                Flow.is_active.is_(True),
                Flow.is_deleted.is_(False),
                Flow.deleted_at.is_(None),
            )
        ).scalars().first()
        if current_flow is not None:
            return current_flow

    active_flows = db.execute(
        select(Flow)
        .where(
            Flow.tenant_id == tenant_id,
            Flow.is_active.is_(True),
            Flow.is_deleted.is_(False),
            Flow.deleted_at.is_(None),
            Flow.published_version_id.is_not(None),
        )
        .order_by(Flow.priority.desc(), Flow.created_at.asc(), Flow.id.asc())
    ).scalars().all()
    if len(active_flows) > 1:
        logger.error(
            "%s tenant_id=%s active_count=%s flow_ids=%s source=runtime_selector",
            MULTIPLE_ACTIVE_FLOWS_LOG,
            tenant_id,
            len(active_flows),
            [str(flow.id) for flow in active_flows],
        )
        raise RuntimeError("Multiple active flows found for tenant")
    return active_flows[0] if active_flows else None


def bind_conversation_to_flow(db: Session, *, conversation: Conversation, flow: Flow) -> None:
    if conversation.current_flow_id != flow.id or conversation.mode != "flow":
        conversation.current_flow_id = flow.id
        conversation.mode = "flow"
        db.add(conversation)
        db.flush()


def _compact_string(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _enqueue_whatsapp_text(
    *,
    recipient_id: str,
    text: str,
    tenant_id: Any | None = None,
    session_id: Any | None = None,
    conversation_id: Any | None = None,
    contact_id: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = dict(metadata or {})
    resolved_tenant_id = _compact_string(tenant_id) or _compact_string(metadata.get("tenant_id"))
    resolved_session_id = _compact_string(session_id) or _compact_string(metadata.get("session_id"))
    resolved_conversation_id = _compact_string(conversation_id) or _compact_string(metadata.get("conversation_id"))
    resolved_contact_id = _compact_string(contact_id) or _compact_string(metadata.get("contact_id"))
    payload = {
        "tenant_id": resolved_tenant_id or "",
        "provider_id": _compact_string(metadata.get("provider_id")),
        "phone": recipient_id,
        "text": text,
        "conversation_id": resolved_conversation_id,
        "contact_id": resolved_contact_id,
        "session_id": resolved_session_id,
        "flow_id": _compact_string(metadata.get("flow_id")),
        "flow_version_id": _compact_string(metadata.get("flow_version_id")),
        "node_id": _compact_string(metadata.get("node_id")),
        "node_type": _compact_string(metadata.get("node_type")),
        "correlation_id": _compact_string(metadata.get("correlation_id") or metadata.get("message_id") or metadata.get("webhook_id")),
        "metadata": metadata,
        "flow_send_source": "flow_runtime_selector:v2",
    }
    logger.info(
        "[V2 ENQUEUE] tenant_id=%s provider_id=%s session_id=%s conversation_id=%s contact_id=%s node_id=%s phone=%s metadata_keys=%s",
        payload.get("tenant_id") or "",
        payload.get("provider_id"),
        payload.get("session_id"),
        payload.get("conversation_id"),
        payload.get("contact_id"),
        payload.get("node_id"),
        recipient_id,
        sorted(metadata.keys()),
    )
    enqueue_send_message(payload)
    return {"status": "queued", "channel": "whatsapp", "type": "text", "recipient_id": recipient_id, "tenant_id": payload.get("tenant_id")}


class FlowRuntimeSelector:
    """Routes an inbound message to Runtime V1 or Runtime V2 from flow.runtime."""

    def __init__(self, *, runtime_worker: FlowV2RuntimeWorker | None = None) -> None:
        self.runtime_worker = runtime_worker

    def dispatch(
        self,
        *,
        db: Session,
        flow: Flow | None,
        tenant_id: UUID,
        phone: str,
        message_text: str,
        conversation: Conversation | None = None,
        contact_id: UUID | None = None,
        input_message_id: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> FlowRuntimeDispatchResult:
        runtime = resolve_flow_runtime(flow)
        if is_conversation_human(conversation):
            logger.info(
                "[FLOW RUNTIME SKIPPED] reason=human_mode tenant_id=%s flow_id=%s conversation_id=%s",
                tenant_id,
                getattr(flow, "id", None),
                getattr(conversation, "id", None),
            )
            return FlowRuntimeDispatchResult(runtime=runtime, processed_by_v2=False, automation_skipped=True)
        if runtime == FLOW_RUNTIME_V1:
            return FlowRuntimeDispatchResult(runtime=FLOW_RUNTIME_V1)

        if flow is None:
            raise RuntimeError("Runtime V2 requires a selected flow")
        if not flow.published_version_id:
            raise RuntimeError(f"Runtime V2 flow {flow.id} has no published_version_id")

        runtime_metadata = dict(metadata or {})
        runtime_metadata.setdefault("tenant_id", str(tenant_id))
        runtime_metadata.setdefault("flow_id", str(flow.id))
        runtime_metadata.setdefault("flow_version_id", str(flow.published_version_id))
        runtime_metadata.setdefault("conversation_id", str(conversation.id) if conversation else None)
        runtime_metadata.setdefault("contact_id", str(contact_id) if contact_id else None)
        runtime_metadata.setdefault("flow_runtime_selector", FLOW_RUNTIME_SELECTOR)
        runtime_choice_key = resolve_runtime_choice_key(runtime_metadata)
        if runtime_choice_key:
            # Materialize the canonical provider-independent key before the
            # RuntimeInput boundary so every diagnostic stage reports the same
            # value (including WhatsApp button_reply.id).
            runtime_metadata.setdefault("runtime_choice_key", runtime_choice_key)
        # Interactive IDs may happen to equal a restart word.  They are Choice
        # selections, not typed restart commands.
        is_interactive_reply = bool(
            runtime_metadata.get("interactive_type")
            or runtime_metadata.get("interactive_reply_id")
            or runtime_metadata.get("selected_row_id")
        )
        if not is_interactive_reply and is_restart_keyword(message_text):
            runtime_metadata["restart_keyword"] = normalize_restart_keyword(message_text)
            runtime_metadata["auto_restart_flow"] = True
        selection_reason = runtime_metadata.get("selected_flow_reason") or (
            "conversation_current_flow_id" if conversation and getattr(conversation, "current_flow_id", None) == flow.id else "provided_flow"
        )
        if runtime_metadata.get("restart_keyword"):
            selection_reason = "restart_keyword"
        logger.info(
            "[V2 FLOW SELECTED]\ntenant_id=%s\nflow_id=%s\nflow_version_id=%s\nreason=%s",
            tenant_id,
            flow.id,
            flow.published_version_id,
            selection_reason,
        )
        logger.info(
            "[CHOICE PARSED] source=FlowRuntimeSelector message_text=%s interactive_type=%s interactive_reply_id=%s selected_row_id=%s selected_title=%s row_id=%s sourceHandle=%s expected_runtime_choice_key=row_id_or_sourceHandle",
            message_text,
            runtime_metadata.get("interactive_type"),
            runtime_metadata.get("interactive_reply_id"),
            runtime_metadata.get("selected_row_id"),
            runtime_metadata.get("selected_title"),
            runtime_metadata.get("row_id"),
            runtime_metadata.get("sourceHandle"),
        )
        logger.info(
            "event=meta_webhook_interactive_pipeline stage=flow_runtime_selector input_message_id=%s "
            "message.type=%s interactive.type=%s button_reply.id=%s interactive_reply_id=%s "
            "selected_row_id=%s row_id=%s runtime_choice_key=%s message_text=%s current_node_id=%s next_node_id=%s",
            input_message_id or "n/a",
            runtime_metadata.get("message_type") or "n/a",
            runtime_metadata.get("interactive_type") or "n/a",
            runtime_metadata.get("interactive_reply_id") or "n/a",
            runtime_metadata.get("interactive_reply_id") or "n/a",
            runtime_metadata.get("selected_row_id") or "n/a",
            runtime_metadata.get("row_id") or "n/a",
            runtime_choice_key or "n/a",
            message_text or "n/a",
            runtime_metadata.get("current_node_id") or "n/a",
            runtime_metadata.get("next_node_id") or "n/a",
        )
        worker = self.runtime_worker or FlowV2RuntimeWorker(
            channel_adapter=WhatsAppAdapter(client=_enqueue_whatsapp_text),
        )
        result = worker.process(
            db,
            FlowV2InputEvent(
                tenant_id=tenant_id,
                flow_version_id=flow.published_version_id,
                external_user_id=phone,
                message_text=message_text,
                contact_id=contact_id,
                conversation_id=conversation.id if conversation else None,
                input_message_id=input_message_id,
                message_id=input_message_id,
                webhook_id=input_message_id,
                metadata=runtime_metadata,
            ),
        )
        logger.info(
            "[FLOW RUNTIME SELECTOR] runtime=v2 tenant_id=%s flow_id=%s flow_version_id=%s conversation_id=%s session_id=%s emitted_events=%s",
            tenant_id,
            flow.id,
            flow.published_version_id,
            getattr(conversation, "id", None),
            result.runtime_output.session_id,
            result.runtime_output.emitted_event_count,
        )
        return FlowRuntimeDispatchResult(runtime=FLOW_RUNTIME_V2, processed_by_v2=True, worker_result=result)
