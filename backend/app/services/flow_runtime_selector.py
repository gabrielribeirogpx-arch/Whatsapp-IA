from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.flow_v2.channel_adapter import WhatsAppAdapter
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


@dataclass(frozen=True)
class FlowRuntimeDispatchResult:
    runtime: str
    processed_by_v2: bool = False
    worker_result: FlowV2WorkerResult | None = None

    @property
    def should_run_v1(self) -> bool:
        return self.runtime == FLOW_RUNTIME_V1 and not self.processed_by_v2


def resolve_flow_runtime(flow: Flow | None) -> str:
    """Return the runtime for a flow, keeping legacy/missing values on V1."""

    runtime = str(getattr(flow, "runtime", "") or "").strip().lower()
    if runtime == FLOW_RUNTIME_V2:
        return FLOW_RUNTIME_V2
    return FLOW_RUNTIME_V1


def resolve_runtime_flow_for_conversation(
    *,
    db: Session,
    tenant_id: UUID,
    conversation: Conversation,
    message_text: str,
) -> Flow | None:
    """Find the flow whose runtime should handle this inbound WhatsApp message."""

    current_flow_id = getattr(conversation, "current_flow_id", None) or getattr(conversation, "current_flow", None)
    if current_flow_id:
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
        selection_reason = runtime_metadata.get("selected_flow_reason") or (
            "conversation_current_flow_id" if conversation and getattr(conversation, "current_flow_id", None) == flow.id else "provided_flow"
        )
        logger.info(
            "[V2 FLOW SELECTED]\ntenant_id=%s\nflow_id=%s\nflow_version_id=%s\nreason=%s",
            tenant_id,
            flow.id,
            flow.published_version_id,
            selection_reason,
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
