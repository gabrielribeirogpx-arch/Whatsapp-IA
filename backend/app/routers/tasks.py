from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Contact, Conversation, ConversationLog, Task, Tenant, TenantUser
from app.routers.account import _decode_token
from app.services.audit_service import write_audit_log
from app.services.realtime_service import publish_dashboard_event, sse_broker
from app.services.tenant_service import get_current_tenant

router = APIRouter(tags=["tasks"])

ALLOWED_TASK_STATUSES = {"open", "in_progress", "completed"}
ALLOWED_TASK_PRIORITIES = {"low", "normal", "high", "urgent"}


class TaskOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    conversation_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    lead_id: uuid.UUID | None = None
    title: str
    description: str | None = None
    priority: str
    status: str
    assigned_to: str | None = None
    due_at: datetime | None = None
    completed_at: datetime | None = None
    completed_by: uuid.UUID | None = None
    created_at: datetime
    updated_at: datetime
    contact_name: str | None = None
    contact_phone: str | None = None
    conversation_name: str | None = None
    conversation_phone: str | None = None

    model_config = ConfigDict(from_attributes=True)


class TaskUpdateIn(BaseModel):
    status: str | None = Field(default=None, max_length=32)
    assigned_to: str | None = Field(default=None, max_length=150)
    priority: str | None = Field(default=None, max_length=16)
    due_at: datetime | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None


def _current_user_or_none(
    *,
    db: Session,
    tenant: Tenant,
    authorization: str = "",
) -> TenantUser | None:
    if not authorization.lower().startswith("bearer "):
        return None
    try:
        payload = _decode_token(authorization.split(" ", 1)[1].strip())
    except HTTPException:
        return None
    if str(payload.get("tenant_id")) != str(tenant.id):
        return None
    email = str(payload.get("email") or "").strip().lower()
    if not email:
        return None
    return (
        db.execute(select(TenantUser).where(TenantUser.tenant_id == tenant.id, TenantUser.email == email))
        .scalars()
        .first()
    )


def _task_query(tenant_id: uuid.UUID):
    return (
        select(Task, Contact, Conversation)
        .outerjoin(Contact, (Contact.id == Task.contact_id) & (Contact.tenant_id == Task.tenant_id))
        .outerjoin(Conversation, (Conversation.id == Task.conversation_id) & (Conversation.tenant_id == Task.tenant_id))
        .where(Task.tenant_id == tenant_id)
    )


def _serialize_task(task: Task, contact: Contact | None = None, conversation: Conversation | None = None) -> TaskOut:
    return TaskOut(
        id=task.id,
        tenant_id=task.tenant_id,
        conversation_id=task.conversation_id,
        contact_id=task.contact_id,
        lead_id=task.lead_id,
        title=task.title,
        description=task.description,
        priority=task.priority,
        status=task.status,
        assigned_to=task.assigned_to,
        due_at=task.due_at,
        completed_at=getattr(task, "completed_at", None),
        completed_by=getattr(task, "completed_by", None),
        created_at=task.created_at,
        updated_at=task.updated_at,
        contact_name=getattr(contact, "name", None),
        contact_phone=getattr(contact, "phone", None),
        conversation_name=getattr(conversation, "name", None),
        conversation_phone=getattr(conversation, "phone_number", None),
    )


def _event_payload(event: str, task_out: TaskOut, action: str) -> dict[str, Any]:
    return {
        "event": event,
        "type": event,
        "action": action,
        "refresh": ["tasks", "activity", "conversations"],
        "tenant_id": str(task_out.tenant_id),
        "conversation_id": str(task_out.conversation_id) if task_out.conversation_id else None,
        "contact_id": str(task_out.contact_id) if task_out.contact_id else None,
        "task": task_out.model_dump(mode="json"),
    }


async def _publish_task_event(event: str, task_out: TaskOut, action: str) -> None:
    payload = _event_payload(event, task_out, action)
    await publish_dashboard_event(tenant_id=task_out.tenant_id, payload=payload)
    if task_out.conversation_id:
        await sse_broker.publish(f"{task_out.tenant_id}:{task_out.conversation_id}", payload)
    if task_out.conversation_phone:
        await sse_broker.publish(f"{task_out.tenant_id}:{task_out.conversation_phone}", payload)


def _get_task_row_or_404(db: Session, tenant_id: uuid.UUID, task_id: uuid.UUID):
    row = db.execute(_task_query(tenant_id).where(Task.id == task_id)).first()
    if not row:
        raise HTTPException(status_code=404, detail="Tarefa não encontrada")
    return row


@router.get("/tasks", response_model=list[TaskOut])
def list_tasks(
    status: str | None = None,
    priority: str | None = None,
    assigned_to: str | None = None,
    overdue: bool = False,
    conversation_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    query = _task_query(tenant.id)
    if status:
        query = query.where(Task.status == status)
    if priority:
        query = query.where(Task.priority == priority)
    if assigned_to:
        query = query.where(Task.assigned_to == assigned_to)
    if conversation_id:
        query = query.where(Task.conversation_id == conversation_id)
    if contact_id:
        query = query.where(Task.contact_id == contact_id)
    if overdue:
        query = query.where(Task.due_at.is_not(None), Task.due_at < datetime.utcnow(), Task.status != "completed")

    rows = db.execute(query.order_by(Task.due_at.is_(None), Task.due_at.asc(), Task.created_at.desc())).all()
    return [_serialize_task(task, contact, conversation) for task, contact, conversation in rows]


@router.patch("/tasks/{task_id}", response_model=TaskOut)
async def update_task(
    task_id: uuid.UUID,
    payload: TaskUpdateIn,
    request: Request,
    authorization: str = Header(default=""),
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    task, _contact, _conversation = _get_task_row_or_404(db, tenant.id, task_id)
    data = payload.model_dump(exclude_unset=True)
    if "status" in data and data["status"] is not None and data["status"] not in ALLOWED_TASK_STATUSES:
        raise HTTPException(status_code=422, detail="Status de tarefa inválido")
    if "priority" in data and data["priority"] is not None and data["priority"] not in ALLOWED_TASK_PRIORITIES:
        raise HTTPException(status_code=422, detail="Prioridade de tarefa inválida")

    before = {field: getattr(task, field) for field in data.keys()}
    for field, value in data.items():
        setattr(task, field, value)
    task.updated_at = datetime.utcnow()

    current_user = _current_user_or_none(db=db, tenant=tenant, authorization=authorization)
    write_audit_log(
        db,
        action="TASK_UPDATED",
        tenant_id=tenant.id,
        user_id=getattr(current_user, "id", None),
        entity_type="task",
        entity_id=task.id,
        metadata={"before": before, "after": data},
        request=request,
    )
    db.add(task)
    db.commit()

    refreshed = _get_task_row_or_404(db, tenant.id, task_id)
    task_out = _serialize_task(*refreshed)
    await _publish_task_event("task_updated", task_out, "TASK_UPDATED")
    return task_out


@router.post("/tasks/{task_id}/complete", response_model=TaskOut)
async def complete_task(
    task_id: uuid.UUID,
    request: Request,
    authorization: str = Header(default=""),
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    task, _contact, _conversation = _get_task_row_or_404(db, tenant.id, task_id)
    now = datetime.utcnow()
    current_user = _current_user_or_none(db=db, tenant=tenant, authorization=authorization)

    task.status = "completed"
    task.updated_at = now
    if hasattr(task, "completed_at"):
        task.completed_at = now
    if hasattr(task, "completed_by") and current_user:
        task.completed_by = current_user.id

    write_audit_log(
        db,
        action="TASK_COMPLETED",
        tenant_id=tenant.id,
        user_id=getattr(current_user, "id", None),
        entity_type="task",
        entity_id=task.id,
        metadata={"status": "completed", "completed_by": str(current_user.id) if current_user else None},
        request=request,
    )
    if task.conversation_id:
        db.add(
            ConversationLog(
                tenant_id=tenant.id,
                conversation_id=task.conversation_id,
                message=f"Tarefa concluída: {task.title}",
                mode="human",
                intent="task_completed",
                used_fallback=False,
                response="Tarefa concluída",
                created_at=now,
            )
        )
    db.add(task)
    db.commit()

    refreshed = _get_task_row_or_404(db, tenant.id, task_id)
    task_out = _serialize_task(*refreshed)
    await _publish_task_event("task_completed", task_out, "TASK_COMPLETED")
    return task_out
