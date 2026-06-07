from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Conversation, Tenant, TenantUser
from app.routers.account import get_current_user
from app.services.admin_conversation_reset_service import reset_test_conversation
from app.services.audit_service import write_audit_log
from app.services.tenant_service import get_current_tenant

router = APIRouter(prefix="/api/admin", tags=["admin"])

ADMIN_ROLES = {"owner", "admin"}


@router.post("/reset-conversation/{conversation_id}")
def reset_conversation(
    conversation_id: UUID,
    request: Request,
    tenant: Tenant = Depends(get_current_tenant),
    current_user: TenantUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if (current_user.role or "").lower() not in ADMIN_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Apenas administradores podem resetar conversas de teste",
        )

    conversation = (
        db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant.id,
            )
        )
        .scalars()
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    result = reset_test_conversation(db, conversation=conversation)
    write_audit_log(
        db,
        action="TEST_CONVERSATION_RESET",
        tenant_id=tenant.id,
        user_id=current_user.id,
        entity_type="conversation",
        entity_id=conversation_id,
        metadata={
            "conversation_id": str(result.conversation_id),
            "contact_id": str(result.contact_id) if result.contact_id else None,
            "phone_number": result.phone_number,
            "deleted_scheduled_jobs": result.deleted_scheduled_jobs,
            "deleted_flow_events": result.deleted_flow_events,
            "deleted_flow_sessions": result.deleted_flow_sessions,
            "deleted_messages": result.deleted_messages,
            "deleted_conversation_logs": result.deleted_conversation_logs,
            "deleted_flow_events_v1": result.deleted_flow_events_v1,
            "deleted_flow_execution_events": result.deleted_flow_execution_events,
            "deleted_flow_executions": result.deleted_flow_executions,
            "detached_leads": result.detached_leads,
            "deleted_conversations": result.deleted_conversations,
        },
        request=request,
    )
    db.commit()

    return {
        "ok": True,
        "conversation_id": str(result.conversation_id),
        "contact_id": str(result.contact_id) if result.contact_id else None,
        "tenant_id": str(result.tenant_id),
        "phone_number": result.phone_number,
        "deleted": {
            "scheduled_jobs": result.deleted_scheduled_jobs,
            "flow_events": result.deleted_flow_events,
            "flow_sessions": result.deleted_flow_sessions,
            "messages": result.deleted_messages,
            "conversation_logs": result.deleted_conversation_logs,
            "flow_events_v1": result.deleted_flow_events_v1,
            "flow_execution_events": result.deleted_flow_execution_events,
            "flow_executions": result.deleted_flow_executions,
            "detached_leads": result.detached_leads,
            "conversations": result.deleted_conversations,
        },
    }
