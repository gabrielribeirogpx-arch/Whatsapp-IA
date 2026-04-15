import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, load_only

from backend.app.database import get_db
from backend.app.models import Conversation, Message, Tenant
from backend.app.schemas.chat import (
    ConversationOut,
    MessageOut,
    SendMessageRequest,
    TenantLoginRequest,
    TenantLoginResponse,
    TenantUsageOut,
    ToggleAssignmentResponse,
)
from backend.app.services.message_service import sanitize_phone, sanitize_text
from backend.app.services.realtime_service import sse_broker
from backend.app.services.tenant_service import (
    TenantLimitError,
    assert_tenant_can_send,
    consume_usage,
    get_current_tenant,
    login_tenant,
)
from backend.app.services.whatsapp_service import WhatsAppConfigError, enviar_mensagem

router = APIRouter(prefix="/api", tags=["chat"])


def _usage_response(tenant: Tenant) -> TenantUsageOut:
    return TenantUsageOut(
        plan=tenant.plan,
        is_blocked=tenant.is_blocked,
        max_monthly_messages=tenant.max_monthly_messages,
        messages_used_month=tenant.messages_used_month,
        usage_month=tenant.usage_month,
    )


@router.post("/auth/login", response_model=TenantLoginResponse)
def tenant_login(payload: TenantLoginRequest, db: Session = Depends(get_db)):
    tenant = login_tenant(db, payload.slug.strip())
    if not tenant:
        raise HTTPException(status_code=401, detail="Credenciais inválidas")

    return TenantLoginResponse(
        tenant_id=tenant.id,
        name=tenant.name,
        slug=tenant.slug,
        usage=_usage_response(tenant),
    )


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    print("TENANT ID RECEBIDO:", tenant.id)
    items = (
        db.execute(
            select(Conversation)
            .options(
                load_only(
                    Conversation.id,
                    Conversation.tenant_id,
                    Conversation.phone_number,
                    Conversation.message,
                    Conversation.updated_at,
                )
            )
            .where(Conversation.tenant_id == tenant.id)
            .order_by(desc(Conversation.updated_at), desc(Conversation.id))
        )
        .scalars()
        .all()
    )
    print("CONVERSAS ENCONTRADAS:", len(items))

    response: list[ConversationOut] = []
    for conversation in items:
        last_message_item = (
            db.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(desc(Message.created_at), desc(Message.id))
                .limit(1)
            )
            .scalars()
            .first()
        )

        response.append(
            ConversationOut(
                id=conversation.id,
                tenant_id=conversation.tenant_id,
                phone=getattr(conversation, "phone", None) or conversation.phone_number or "",
                name=getattr(conversation, "name", None) or "Cliente",
                status=getattr(conversation, "status", None) or "human",
                last_message=(last_message_item.text if last_message_item else conversation.message or ""),
                updated_at=conversation.updated_at,
            )
        )

    return response


@router.get("/messages/{phone}", response_model=list[MessageOut])
def get_messages(
    phone: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    sanitized_phone = sanitize_phone(phone)
    items = (
        db.execute(
            select(Message)
            .where(Message.tenant_id == tenant.id, Message.phone == sanitized_phone)
            .order_by(Message.timestamp.asc(), Message.id.asc())
        )
        .scalars()
        .all()
    )
    return items


@router.post("/send-message", response_model=MessageOut)
async def send_message(
    payload: SendMessageRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    phone = sanitize_phone(payload.phone)
    message_text = sanitize_text(payload.message)
    if not phone or not message_text:
        raise HTTPException(status_code=400, detail="Dados inválidos")

    try:
        assert_tenant_can_send(tenant)
    except TenantLimitError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    tenant_id = tenant.id
    print("TENANT ID:", tenant_id, type(tenant_id))

    conversation = (
        db.query(Conversation)
        .options(load_only(Conversation.id, Conversation.tenant_id, Conversation.phone_number, Conversation.status))
        .filter(Conversation.tenant_id == tenant_id, Conversation.phone_number == phone)
        .first()
    )
    if not conversation:
        conversation = Conversation(
            tenant_id=tenant_id,
            phone_number=phone,
            name=sanitize_text(payload.name or "Cliente"),
            status="human",
        )
        db.add(conversation)
        db.flush()

    try:
        enviar_mensagem(phone, message_text, token=tenant.whatsapp_token, phone_number_id=tenant.phone_number_id)
    except WhatsAppConfigError:
        pass

    message = Message(
        tenant_id=tenant_id,
        phone=phone,
        conversation_id=conversation.id,
        role="assistant",
        message=message_text,
        created_at=datetime.utcnow(),
        content=message_text,
        from_me=True,
        timestamp=datetime.utcnow(),
    )
    db.add(message)
    consume_usage(tenant, 1)
    conversation.last_message = message_text
    conversation.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(message)

    await sse_broker.publish(f"{tenant.id}:{phone}", {"event": "message", "message": MessageOut.model_validate(message).model_dump(mode="json")})
    return message


@router.post("/send", response_model=MessageOut)
async def send_message_legacy(payload: SendMessageRequest, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    return await send_message(payload, tenant, db)


@router.post("/take-over/{phone}", response_model=ToggleAssignmentResponse)
def take_over(
    phone: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    sanitized_phone = sanitize_phone(phone)
    conversation = db.execute(
        select(Conversation)
        .options(load_only(Conversation.id, Conversation.tenant_id, Conversation.phone_number, Conversation.status))
        .where(Conversation.tenant_id == tenant.id, Conversation.phone_number == sanitized_phone)
    ).scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    conversation.status = "human" if conversation.status == "bot" else "bot"
    conversation.updated_at = datetime.utcnow()
    db.commit()

    return ToggleAssignmentResponse(phone=sanitized_phone, status=conversation.status)


@router.get("/stream/messages/{phone}")
async def stream_messages(phone: str, tenant: Tenant = Depends(get_current_tenant)):
    sanitized_phone = sanitize_phone(phone)
    channel = f"{tenant.id}:{sanitized_phone}"
    queue = await sse_broker.subscribe(channel)

    async def event_generator():
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=20)
                    yield data
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            sse_broker.unsubscribe(channel, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
