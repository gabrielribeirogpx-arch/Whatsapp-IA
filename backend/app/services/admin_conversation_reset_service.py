from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.orm import Session

from app.models import (
    Conversation,
    ConversationLog,
    FlowEvent,
    FlowExecution,
    FlowExecutionEvent,
    FlowV2Event,
    FlowV2ScheduledJob,
    FlowV2Session,
    Lead,
    Message,
)


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
    deleted_conversation_logs: int
    deleted_flow_events_v1: int
    deleted_flow_execution_events: int
    deleted_flow_executions: int
    detached_leads: int
    deleted_conversations: int


def reset_test_conversation(
    db: Session, *, conversation: Conversation
) -> ResetConversationResult:
    """Delete only the selected test conversation and its Runtime V2 state.

    The contact row is intentionally preserved so a new inbound WhatsApp message can
    recreate the conversation/session as if it were the first contact.
    """

    conversation_id = conversation.id
    contact_id = conversation.contact_id
    tenant_id = conversation.tenant_id
    phone_number = conversation.phone_number

    flow_v2_session_filter = (
        or_(
            FlowV2Session.conversation_id == conversation_id,
            and_(
                FlowV2Session.tenant_id == tenant_id,
                FlowV2Session.external_user_id == phone_number,
            ),
        ),
    )
    session_ids = list(
        db.execute(select(FlowV2Session.id).where(*flow_v2_session_filter)).scalars()
    )

    deleted_scheduled_jobs = 0
    deleted_flow_events = 0
    if session_ids:
        deleted_scheduled_jobs = (
            db.execute(
                delete(FlowV2ScheduledJob).where(
                    FlowV2ScheduledJob.session_id.in_(session_ids)
                )
            ).rowcount
            or 0
        )
        deleted_flow_events = (
            db.execute(
                delete(FlowV2Event).where(FlowV2Event.session_id.in_(session_ids))
            ).rowcount
            or 0
        )

    deleted_flow_sessions = (
        db.execute(delete(FlowV2Session).where(*flow_v2_session_filter)).rowcount or 0
    )

    deleted_messages = (
        db.execute(
            delete(Message).where(Message.conversation_id == conversation_id)
        ).rowcount
        or 0
    )

    deleted_conversation_logs = (
        db.execute(
            delete(ConversationLog).where(
                ConversationLog.conversation_id == conversation_id
            )
        ).rowcount
        or 0
    )

    deleted_flow_events_v1 = (
        db.execute(
            delete(FlowEvent).where(FlowEvent.conversation_id == conversation_id)
        ).rowcount
        or 0
    )

    flow_execution_ids = list(
        db.execute(
            select(FlowExecution.id).where(
                FlowExecution.conversation_id == conversation_id
            )
        ).scalars()
    )
    deleted_flow_execution_events = 0
    if flow_execution_ids:
        deleted_flow_execution_events = (
            db.execute(
                delete(FlowExecutionEvent).where(
                    FlowExecutionEvent.execution_id.in_(flow_execution_ids)
                )
            ).rowcount
            or 0
        )

    deleted_flow_executions = (
        db.execute(
            delete(FlowExecution).where(
                FlowExecution.conversation_id == conversation_id
            )
        ).rowcount
        or 0
    )

    detached_leads = (
        db.execute(
            update(Lead)
            .where(Lead.conversation_id == conversation_id)
            .values(conversation_id=None)
        ).rowcount
        or 0
    )

    deleted_conversations = (
        db.execute(
            delete(Conversation).where(
                Conversation.tenant_id == tenant_id,
                Conversation.id == conversation_id,
            )
        ).rowcount
        or 0
    )

    return ResetConversationResult(
        conversation_id=conversation_id,
        contact_id=contact_id,
        tenant_id=tenant_id,
        phone_number=phone_number,
        deleted_scheduled_jobs=deleted_scheduled_jobs,
        deleted_flow_events=deleted_flow_events,
        deleted_flow_sessions=deleted_flow_sessions,
        deleted_messages=deleted_messages,
        deleted_conversation_logs=deleted_conversation_logs,
        deleted_flow_events_v1=deleted_flow_events_v1,
        deleted_flow_execution_events=deleted_flow_execution_events,
        deleted_flow_executions=deleted_flow_executions,
        detached_leads=detached_leads,
        deleted_conversations=deleted_conversations,
    )
