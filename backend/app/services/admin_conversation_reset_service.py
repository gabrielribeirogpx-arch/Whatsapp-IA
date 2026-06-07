from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models import Conversation, FlowV2Event, FlowV2ScheduledJob, FlowV2Session, Message


@dataclass(frozen=True)
class ResetConversationResult:
    conversation_id: UUID
    contact_id: UUID | None
    tenant_id: UUID
    phone_number: str
    deleted_scheduled_jobs: int
    deleted_flow_events: int
    deleted_flow_sessions: int
    deleted_messages: int
    deleted_conversations: int


def reset_test_conversation(db: Session, *, conversation: Conversation) -> ResetConversationResult:
    """Delete only the selected test conversation and its Runtime V2 state.

    The contact row is intentionally preserved so a new inbound WhatsApp message can
    recreate the conversation/session as if it were the first contact.
    """

    conversation_id = conversation.id
    contact_id = conversation.contact_id
    tenant_id = conversation.tenant_id
    phone_number = conversation.phone_number

    session_ids = list(
        db.execute(
            select(FlowV2Session.id).where(
                FlowV2Session.tenant_id == tenant_id,
                FlowV2Session.external_user_id == phone_number,
            )
        ).scalars()
    )

    deleted_scheduled_jobs = 0
    deleted_flow_events = 0
    if session_ids:
        deleted_scheduled_jobs = db.execute(
            delete(FlowV2ScheduledJob).where(
                FlowV2ScheduledJob.tenant_id == tenant_id,
                FlowV2ScheduledJob.session_id.in_(session_ids),
            )
        ).rowcount or 0
        deleted_flow_events = db.execute(
            delete(FlowV2Event).where(
                FlowV2Event.tenant_id == tenant_id,
                FlowV2Event.session_id.in_(session_ids),
            )
        ).rowcount or 0

    deleted_flow_sessions = db.execute(
        delete(FlowV2Session).where(
            FlowV2Session.tenant_id == tenant_id,
            FlowV2Session.external_user_id == phone_number,
        )
    ).rowcount or 0

    deleted_messages = db.execute(
        delete(Message).where(
            Message.tenant_id == tenant_id,
            Message.conversation_id == conversation_id,
        )
    ).rowcount or 0

    deleted_conversations = db.execute(
        delete(Conversation).where(
            Conversation.tenant_id == tenant_id,
            Conversation.id == conversation_id,
        )
    ).rowcount or 0

    return ResetConversationResult(
        conversation_id=conversation_id,
        contact_id=contact_id,
        tenant_id=tenant_id,
        phone_number=phone_number,
        deleted_scheduled_jobs=deleted_scheduled_jobs,
        deleted_flow_events=deleted_flow_events,
        deleted_flow_sessions=deleted_flow_sessions,
        deleted_messages=deleted_messages,
        deleted_conversations=deleted_conversations,
    )
