import asyncio
from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, load_only, selectinload

from backend.app.database import get_db
from backend.app.models import Contact, Conversation, Message, Tenant
from backend.app.schemas.chat import (
    ContactOut,
    ConversationOut,
    MessageOut,
    SendMessageRequest,
    TenantLoginRequest,
    TenantLoginResponse,
    TenantUsageOut,
    ToggleAssignmentResponse,
)
from backend.app.services.contact_sync_service import ensure_conversation_contact_link, upsert_contact_for_phone
from backend.app.services.lead_service import get_or_create_lead
from backend.app.services.message_service import sanitize_text
from backend.app.utils.phone import normalize_phone
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


def _looks_like_name(text: str) -> bool:
    if not text:
        return False

    cleaned = text.strip()
    if not cleaned or len(cleaned) > 40:
        return False

    if any(char.isdigit() for char in cleaned):
        return False

    words = cleaned.split()
    return len(words) <= 4


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
    print("TENANT ID:", tenant.id)
    items = (
        db.execute(
            select(Conversation)
            .options(
                load_only(
                    Conversation.id,
                    Conversation.tenant_id,
                    Conversation.contact_id,
                    Conversation.phone_number,
                    Conversation.name,
                    Conversation.avatar_url,
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
    print("CONVERSAS:", items)

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
                contact_id=conversation.contact_id,
                phone=getattr(conversation, "phone", None) or conversation.phone_number or "",
                name=(conversation.name if hasattr(conversation, "name") else None) or conversation.phone_number or "",
                avatar_url=conversation.avatar_url,
                stage=conversation.contact.stage if conversation.contact else "novo",
                score=conversation.contact.score if conversation.contact else 0,
                status=getattr(conversation, "status", None) or "human",
                last_message=(last_message_item.text if last_message_item else ""),
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
    sanitized_phone = normalize_phone(phone)
    print("PHONE_NORMALIZED:", sanitized_phone)
    conversation = db.execute(
        select(Conversation)
        .options(load_only(Conversation.id))
        .where(Conversation.tenant_id == tenant.id, Conversation.phone_number == sanitized_phone)
        .order_by(desc(Conversation.updated_at), desc(Conversation.id))
    ).scalars().first()
    if not conversation:
        return []

    items = (
        db.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
        .scalars()
        .all()
    )
    return items




@router.get("/messages/conversation/{conversation_id}", response_model=list[MessageOut])
def get_messages_by_conversation(
    conversation_id: UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    items = (
        db.execute(
            select(Message)
            .where(Message.tenant_id == tenant.id, Message.conversation_id == conversation_id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
        .scalars()
        .all()
    )
    return items

@router.get("/messages/by-contact/{contact_id}", response_model=list[MessageOut])
def get_messages_by_contact(
    contact_id: UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    conversation = db.execute(
        select(Conversation)
        .options(load_only(Conversation.id))
        .where(Conversation.tenant_id == tenant.id, Conversation.contact_id == contact_id)
        .order_by(desc(Conversation.updated_at), desc(Conversation.id))
    ).scalars().first()
    if not conversation:
        return []

    items = (
        db.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(Message.created_at.asc(), Message.id.asc())
        )
        .scalars()
        .all()
    )
    return items


@router.get("/contacts", response_model=list[ContactOut])
def list_contacts(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    return (
        db.execute(
            select(Contact)
            .options(selectinload(Contact.conversations))
            .where(Contact.tenant_id == tenant.id)
            .order_by(desc(Contact.last_message_at), desc(Contact.created_at), desc(Contact.id))
        )
        .scalars()
        .all()
    )


@router.post("/send-message", response_model=MessageOut)
async def send_message(
    payload: SendMessageRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    phone = normalize_phone(payload.phone)
    print("PHONE_NORMALIZED:", phone)
    message_text = sanitize_text(payload.message)
    if not phone or not message_text:
        raise HTTPException(status_code=400, detail="Dados inválidos")

    try:
        assert_tenant_can_send(tenant)
    except TenantLimitError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    tenant_id = tenant.id
    print("TENANT ID:", tenant_id, type(tenant_id))

    contact = None
    if payload.contact_id:
        contact = db.execute(
            select(Contact).where(Contact.tenant_id == tenant_id, Contact.id == payload.contact_id)
        ).scalars().first()
        if contact:
            phone = normalize_phone(contact.phone)
            print("PHONE_NORMALIZED:", phone)

    if not contact:
        contact = upsert_contact_for_phone(
            db,
            tenant_id=tenant_id,
            phone=phone,
            name=payload.name,
        )

    conversation = (
        db.query(Conversation)
        .options(load_only(Conversation.id, Conversation.tenant_id, Conversation.phone_number, Conversation.updated_at, Conversation.contact_id))
        .filter(Conversation.tenant_id == tenant_id, Conversation.phone_number == phone)
        .order_by(desc(Conversation.updated_at), desc(Conversation.id))
        .first()
    )
    if not conversation:
        conversation = Conversation(
            tenant_id=tenant_id,
            contact_id=contact.id,
            phone_number=phone,
            name=None,
        )
        db.add(conversation)
        db.flush()
    else:
        ensure_conversation_contact_link(conversation, contact)

    if payload.name and payload.name.strip() and payload.name.strip() != contact.name:
        contact.name = payload.name.strip()
    if conversation.name is None and _looks_like_name(message_text):
        conversation.name = message_text.strip()
        if not contact.name or contact.name == "Cliente":
            contact.name = conversation.name
    print("NOME CLIENTE:", conversation.name)

    try:
        enviar_mensagem(phone, message_text, token=tenant.whatsapp_token, phone_number_id=tenant.phone_number_id)
    except WhatsAppConfigError:
        pass

    print("SALVANDO_MSG:", phone, message_text)
    message = Message(
        tenant_id=conversation.tenant_id,
        conversation_id=conversation.id,
        text=message_text,
        created_at=datetime.utcnow(),
        from_me=True,
    )
    db.add(message)
    print("CONVERSA_ID:", conversation.id)
    print("MSG_SALVA:", message.text)
    print("LEAD_SYNC:", phone, tenant.id)
    get_or_create_lead(
        db=db,
        tenant_id=tenant.id,
        phone=conversation.phone_number or phone,
        name=conversation.name,
        last_message=message_text,
    )
    consume_usage(tenant, 1)
    contact.last_message_at = datetime.utcnow()
    conversation.message = message_text
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
    sanitized_phone = normalize_phone(phone)
    print("PHONE_NORMALIZED:", sanitized_phone)
    conversation = db.execute(
        select(Conversation)
        .options(load_only(Conversation.id, Conversation.tenant_id, Conversation.phone_number))
        .where(Conversation.tenant_id == tenant.id, Conversation.phone_number == sanitized_phone)
    ).scalars().first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    conversation.updated_at = datetime.utcnow()
    db.commit()

    return ToggleAssignmentResponse(phone=sanitized_phone, status="human")


@router.get("/stream/messages/{phone}")
async def stream_messages(phone: str, tenant: Tenant = Depends(get_current_tenant)):
    sanitized_phone = normalize_phone(phone)
    print("PHONE_NORMALIZED:", sanitized_phone)
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
