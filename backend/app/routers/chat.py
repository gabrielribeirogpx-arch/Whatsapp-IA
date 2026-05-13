import asyncio
import logging
from datetime import datetime
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, load_only, selectinload

from app.database import get_db
from app.models import Contact, Conversation, ConversationLog, Message, Tenant
from app.schemas.chat import (
    ContactOut,
    ConversationOut,
    ConversationLogOut,
    MessageOut,
    SendMessageRequest,
    TenantLoginRequest,
    TenantLoginResponse,
    TenantUsageOut,
    ToggleAssignmentResponse,
)
from app.services.contact_sync_service import ensure_conversation_contact_link, upsert_contact_for_phone
from app.services.bot_service import handle_bot_activation
from app.services.conversation_service import get_or_create_conversation
from app.services.lead_service import get_or_create_lead
from app.services.message_service import sanitize_text
from app.utils.phone import normalize_phone
from app.services.realtime_service import sse_broker
from app.services.tenant_service import (
    TenantLimitError,
    assert_tenant_can_send,
    consume_usage,
    get_current_tenant,
    login_tenant,
)
from app.services.queue import enqueue_send_message

router = APIRouter(tags=["chat"])
logger = logging.getLogger(__name__)


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
    try:
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
                        Conversation.mode,
                        Conversation.updated_at,
                    )
                )
                .where(Conversation.tenant_id == tenant.id)
                .order_by(desc(Conversation.updated_at), desc(Conversation.id))
            )
            .scalars()
            .all()
        )

        response: list[ConversationOut] = []
        seen_phones: set[str] = set()
        for conversation in items or []:
            phone = str(getattr(conversation, "phone", None) or conversation.phone_number or "").strip()
            if not phone:
                phone = "desconhecido"
            if phone in seen_phones:
                continue
            seen_phones.add(phone)

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

            contact = getattr(conversation, "contact", None)
            contact_name = getattr(contact, "name", None) if contact else None
            display_name = (getattr(conversation, "name", None) or contact_name or phone).strip() or phone
            stage = getattr(contact, "stage", None) if contact else None
            score = getattr(contact, "score", None) if contact else None
            last_message = getattr(last_message_item, "text", "") if last_message_item else ""

            response.append(
                ConversationOut(
                    id=conversation.id,
                    tenant_id=conversation.tenant_id,
                    contact_id=conversation.contact_id,
                    phone=phone,
                    name=display_name,
                    avatar_url=conversation.avatar_url,
                    stage=stage or "novo",
                    score=int(score or 0),
                    mode=conversation.mode or "bot",
                    last_message=last_message or "",
                    updated_at=conversation.updated_at or datetime.utcnow(),
                )
            )

        return response
    except Exception as exc:
        logger.exception(
            "[CONVERSATIONS LIST ERROR] tenant_id=%s error_type=%s error_message=%s",
            getattr(tenant, "id", None),
            type(exc).__name__,
            str(exc),
        )
        return []


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




@router.get("/messages/conversation/{conversation_id}", response_model=List[MessageOut])
def get_messages_by_conversation(
    conversation_id: UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    return messages

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


@router.get("/logs", response_model=list[ConversationLogOut])
def get_conversation_logs(
    conversation_id: UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    logs = (
        db.execute(
            select(ConversationLog)
            .where(
                ConversationLog.tenant_id == tenant.id,
                ConversationLog.conversation_id == conversation_id,
            )
            .order_by(ConversationLog.created_at.asc(), ConversationLog.id.asc())
        )
        .scalars()
        .all()
    )
    return logs




@router.get("/contacts/debug-count")
def contacts_debug_count(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    contacts = db.execute(select(Contact).where(Contact.tenant_id == tenant.id)).scalars().all()
    phones = [str(getattr(contact, "phone", "") or "") for contact in contacts]
    return {"tenant_id": str(tenant.id), "count": len(contacts), "phones": phones}
@router.get("/contacts")
def list_contacts(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    tag: str | None = Query(default=None),
    source: str | None = Query(default=None),
    search: str | None = Query(default=None),
    interacted_after: datetime | None = Query(default=None),
    last_interaction_after: datetime | None = Query(default=None),
):
    print("[CONTACTS API HIT]")
    try:
        query = select(Contact).options(selectinload(Contact.conversations)).where(Contact.tenant_id == tenant.id)

        contacts = (
            db.execute(query.order_by(desc(Contact.last_interaction_at), desc(Contact.created_at), desc(Contact.id)))
            .scalars()
            .all()
        )

        logger.info(
            "[CONTACTS LIST] tenant_id=%s count=%s query_params=%s",
            tenant.id,
            len(contacts),
            {
                "tag": (tag or "").strip(),
                "source": (source or "").strip(),
                "search": (search or "").strip(),
                "interacted_after": interacted_after.isoformat() if interacted_after else None,
                "last_interaction_after": last_interaction_after.isoformat() if last_interaction_after else None,
            },
        )

        print("[CONTACTS API DEBUG]")
        print("tenant_id=", tenant.id)
        print("contacts_count=", len(contacts))

        try:
            print("first_contact=", {
                "id": str(contacts[0].id),
                "phone": contacts[0].phone,
                "name": contacts[0].name,
            })
        except Exception as e:
            print("first_contact_error=", str(e))

        return {
            "success": True,
            "items": [
                {
                    "id": str(c.id),
                    "phone": c.phone,
                    "name": c.name,
                    "source": c.source,
                    "tags_json": c.tags_json or [],
                    "custom_fields_json": c.custom_fields_json or {},
                    "last_order_id": c.last_order_id,
                    "city": c.city,
                    "company": c.company,
                    "plan": c.plan,
                    "lifecycle_stage": c.lifecycle_stage,
                    "notes": c.notes,
                    "last_interaction_at": c.last_interaction_at.isoformat() if c.last_interaction_at else None,
                }
                for c in contacts
            ]
        }
    except Exception as exc:
        print(f"[CONTACTS API ERROR] {type(exc).__name__}: {str(exc)}")
        logger.exception(
            "[CONTACTS LIST ERROR] tenant_id=%s exception_type=%s message=%s",
            tenant.id,
            type(exc).__name__,
            str(exc),
        )
        return {
            "success": True,
            "items": [],
            "error": "Não foi possível carregar contatos no momento.",
        }


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

    conversation, _ = get_or_create_conversation(
        db=db,
        tenant_id=tenant_id,
        phone=phone,
        contact_id=contact.id if contact else None,
    )
    ensure_conversation_contact_link(conversation, contact)

    if contact and payload.name and payload.name.strip() and payload.name.strip() != contact.name:
        contact.name = payload.name.strip()
    if conversation.name is None and _looks_like_name(message_text):
        conversation.name = message_text.strip()
        if contact and (not contact.name or contact.name == "Cliente"):
            contact.name = conversation.name
    print("NOME CLIENTE:", conversation.name)

    print(f"[MODE CHECK] current mode={conversation.mode}")
    try:
        enqueue_send_message({"tenant_id": tenant.id, "phone": phone, "text": message_text})
    except Exception:
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
    if contact:
        contact.last_message_at = datetime.utcnow()
    conversation.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(message)

    message_payload = {"event": "message", "message": MessageOut.model_validate(message).model_dump(mode="json")}
    await sse_broker.publish(f"{tenant.id}:{phone}", message_payload)
    await sse_broker.publish(f"{tenant.id}:{conversation.id}", message_payload)
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


@router.patch("/conversations/{conversation_id}/mode")
def update_conversation_mode(
    conversation_id: UUID,
    mode: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
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
        raise HTTPException(status_code=404, detail="Conversation not found")

    if mode not in {"human", "bot", "ai", "flow"}:
        raise HTTPException(status_code=400, detail="Invalid mode")

    conversation.mode = mode
    conversation.updated_at = datetime.utcnow()

    if mode == "bot":
        handle_bot_activation(db=db, conversation=conversation)

    db.commit()

    return {"status": "updated", "mode": mode}


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


@router.get("/sse/messages/{conversation_id}")
async def stream_messages_by_conversation(
    conversation_id: UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    conversation = (
        db.execute(
            select(Conversation)
            .options(load_only(Conversation.id))
            .where(
                Conversation.id == conversation_id,
                Conversation.tenant_id == tenant.id,
            )
        )
        .scalars()
        .first()
    )
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    channel = f"{tenant.id}:{conversation.id}"
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




@router.patch("/contacts/{contact_id}")
def update_contact(
    contact_id: UUID,
    payload: dict,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    contact = db.execute(select(Contact).where(Contact.tenant_id == tenant.id, Contact.id == contact_id)).scalars().first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")

    if "name" in payload:
        contact.name = str(payload.get("name") or "").strip() or None
    if "first_name" in payload:
        contact.first_name = str(payload.get("first_name") or "").strip() or None
    if "last_name" in payload:
        contact.last_name = str(payload.get("last_name") or "").strip() or None
    if "email" in payload:
        contact.email = str(payload.get("email") or "").strip() or None
    if "tags" in payload and isinstance(payload.get("tags"), list):
        contact.tags_json = [str(tag).strip() for tag in payload.get("tags") if str(tag).strip()]
    if "custom_fields_json" in payload and isinstance(payload.get("custom_fields_json"), dict):
        contact.custom_fields_json = payload.get("custom_fields_json") or {}

    contact.updated_at = datetime.utcnow()
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return {
        "id": str(contact.id),
        "name": contact.name,
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "email": contact.email,
        "tags_json": contact.tags_json or [],
        "custom_fields_json": contact.custom_fields_json or {},
    }

@router.patch("/contacts/{contact_id}/custom-fields")
def update_contact_custom_fields(
    contact_id: UUID,
    payload: dict,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    contact = db.execute(select(Contact).where(Contact.tenant_id == tenant.id, Contact.id == contact_id)).scalars().first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")

    current = contact.custom_fields_json if isinstance(contact.custom_fields_json, dict) else {}
    incoming = payload if isinstance(payload, dict) else {}
    reserved = {"name", "tags_json", "last_order_id", "city", "company", "plan", "lifecycle_stage", "notes"}
    custom = {k: v for k, v in incoming.items() if k not in reserved}
    contact.custom_fields_json = {**current, **custom}
    if "name" in incoming:
        contact.name = str(incoming.get("name") or "").strip() or None
    if "tags_json" in incoming and isinstance(incoming.get("tags_json"), list):
        contact.tags_json = [str(t).strip() for t in incoming.get("tags_json") if str(t).strip()]
    for key in ["last_order_id", "city", "company", "plan", "lifecycle_stage", "notes"]:
        if key in incoming:
            setattr(contact, key, str(incoming.get(key) or "").strip() or None)
    contact.updated_at = datetime.utcnow()
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return {"success": True, "id": str(contact.id), "custom_fields_json": contact.custom_fields_json}
