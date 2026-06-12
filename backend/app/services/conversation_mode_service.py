from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.services.audit_service import write_audit_log
from app.services.contact_event_service import register_contact_event
from app.services.realtime_service import sync_publish

logger = logging.getLogger(__name__)

CONVERSATION_MODE_CHANGED = "CONVERSATION_MODE_CHANGED"
CONVERSATION_MODES = {"human", "bot", "ai", "flow"}
INBOX_CONVERSATION_MODES = {"human", "bot", "ai"}


class ConversationModeError(ValueError):
    """Controlled error for invalid conversation mode updates."""


def normalize_conversation_mode(mode: str | None, *, allow_flow: bool = False) -> str:
    normalized = str(mode or "").strip().lower()
    allowed_modes = CONVERSATION_MODES if allow_flow else INBOX_CONVERSATION_MODES
    if normalized not in allowed_modes:
        raise ConversationModeError(f"Invalid conversation mode: {mode}")
    return normalized


def _conversation_payload(conversation: Conversation) -> dict[str, Any]:
    updated_at = getattr(conversation, "updated_at", None) or datetime.utcnow()
    contact = getattr(conversation, "contact", None)
    return {
        "id": str(conversation.id),
        "tenant_id": str(conversation.tenant_id),
        "contact_id": str(conversation.contact_id) if getattr(conversation, "contact_id", None) else None,
        "phone": conversation.phone_number,
        "name": (getattr(contact, "name", None) if contact else None) or conversation.name or conversation.phone_number,
        "avatar_url": getattr(conversation, "avatar_url", None),
        "stage": getattr(contact, "stage", None) if contact else "novo",
        "score": int((getattr(contact, "score", None) if contact else 0) or 0),
        "mode": conversation.mode or "bot",
        "assigned_user_id": str(conversation.assigned_user_id) if getattr(conversation, "assigned_user_id", None) else None,
        "assigned_user_name": getattr(conversation, "assigned_user_name", None),
        "last_message": "",
        "updated_at": updated_at.isoformat() if hasattr(updated_at, "isoformat") else str(updated_at),
    }


def _publish_mode_realtime(*, tenant_id: UUID, conversation: Conversation, new_mode: str) -> None:
    conversation_payload = _conversation_payload(conversation)
    activity = {
        "id": str(conversation.id),
        "type": "HUMAN_REQUEST" if new_mode == "human" else "CONVERSATION_MODE_UPDATED",
        "title": conversation.name or conversation.phone_number or "Conversa",
        "description": "Solicitação humana" if new_mode == "human" else f"Modo atualizado para {new_mode}",
        "entity_type": "conversation",
        "entity_id": str(conversation.id),
        "contact_name": conversation.name,
        "phone": conversation.phone_number,
        "created_at": datetime.utcnow().isoformat(),
    }
    dashboard_payload = {
        "event": "conversation_updated",
        "refresh": ["analytics", "conversations"],
        "activity": activity,
        "conversation_id": str(conversation.id),
        "phone": conversation.phone_number,
        "mode": conversation.mode,
        "assigned_user_id": str(conversation.assigned_user_id) if getattr(conversation, "assigned_user_id", None) else None,
        "assigned_user_name": getattr(conversation, "assigned_user_name", None),
        "conversation": conversation_payload,
    }
    assignment_payload = {
        "event": "conversation_assigned",
        "refresh": ["conversations"],
        "conversation_id": str(conversation.id),
        "phone": conversation.phone_number,
        "mode": conversation.mode,
        "assigned_user_id": str(conversation.assigned_user_id) if getattr(conversation, "assigned_user_id", None) else None,
        "assigned_user_name": getattr(conversation, "assigned_user_name", None),
        "conversation": conversation_payload,
    }
    sync_publish(f"dashboard:{tenant_id}", dashboard_payload)
    sync_publish(f"dashboard:{tenant_id}", assignment_payload)
    sync_publish(f"{tenant_id}:{conversation.id}", assignment_payload)
    sync_publish(f"{tenant_id}:{conversation.phone_number}", assignment_payload)


def set_conversation_mode(
    db: Session,
    *,
    tenant_id: UUID,
    conversation: Conversation,
    mode: str,
    flow_execution_id: str | UUID | None = None,
    source: str = "inbox",
    reason: str | None = None,
    user_id: UUID | None = None,
    allow_flow: bool = False,
    commit: bool = False,
    publish_realtime: bool = True,
) -> Conversation:
    new_mode = normalize_conversation_mode(mode, allow_flow=allow_flow)
    if str(getattr(conversation, "tenant_id", "")) != str(tenant_id):
        raise ConversationModeError("Conversation does not belong to tenant")

    old_mode = str(getattr(conversation, "mode", None) or "bot").strip().lower()

    if new_mode == "bot":
        conversation.assigned_user_id = None
        conversation.assigned_user_name = None

    conversation.mode = new_mode
    conversation.updated_at = datetime.utcnow()

    metadata = {
        "tenant_id": str(tenant_id),
        "conversation_id": str(conversation.id),
        "old_mode": old_mode,
        "new_mode": new_mode,
        "flow_execution_id": str(flow_execution_id) if flow_execution_id else None,
        "source": source,
        "reason": reason,
    }
    write_audit_log(
        db,
        action=CONVERSATION_MODE_CHANGED,
        tenant_id=tenant_id,
        user_id=user_id,
        entity_type="conversation",
        entity_id=conversation.id,
        metadata=metadata,
    )

    if getattr(conversation, "contact_id", None):
        try:
            register_contact_event(
                db,
                tenant_id=tenant_id,
                contact_id=conversation.contact_id,
                event_type=CONVERSATION_MODE_CHANGED,
                title="Modo da conversa alterado",
                description=f"{old_mode} → {new_mode}",
                metadata=metadata,
                contact=getattr(conversation, "contact", None),
            )
        except Exception:
            logger.exception(
                "[CONVERSATION MODE CONTACT EVENT FAILED] tenant_id=%s conversation_id=%s",
                tenant_id,
                getattr(conversation, "id", None),
            )

    if hasattr(db, "add"):
        db.add(conversation)
    if commit and hasattr(db, "commit"):
        db.commit()
        if hasattr(db, "refresh"):
            db.refresh(conversation)

    if publish_realtime:
        _publish_mode_realtime(tenant_id=tenant_id, conversation=conversation, new_mode=new_mode)

    logger.info(
        "[CONVERSATION MODE CHANGED] tenant_id=%s conversation_id=%s old_mode=%s new_mode=%s source=%s flow_execution_id=%s",
        tenant_id,
        getattr(conversation, "id", None),
        old_mode,
        new_mode,
        source,
        flow_execution_id,
    )
    return conversation
