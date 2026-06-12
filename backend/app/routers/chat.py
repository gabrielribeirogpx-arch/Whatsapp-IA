import asyncio
import logging
from datetime import datetime
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select, func
from sqlalchemy.orm import Session, load_only, selectinload

from app.database import get_db
from app.db.session import SessionLocal
from app.routers.account import get_current_user
from app.models import Contact, ContactEvent, Conversation, ConversationLog, Message, Tenant, TenantUser
from app.schemas.chat import (
    ContactOut,
    ConversationAssignmentRequest,
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
from app.services.contact_event_service import register_contact_event
from app.services.flow_engine_service import get_active_visual_flow
from app.services.conversation_service import get_or_create_conversation
from app.services.lead_service import get_or_create_lead
from app.services.message_service import sanitize_text
from app.services.websocket_auth import authenticate_ws_user
from app.services.presence_service import PresenceService
from app.utils.phone import normalize_phone
from app.services.realtime_service import publish_dashboard_event, sse_broker
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


def _serialize_contact_summary(contact: Contact) -> dict:
    return {
        "id": str(contact.id),
        "tenant_id": str(contact.tenant_id),
        "name": contact.name,
        "phone": contact.phone,
        "source": contact.source,
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "email": contact.email,
        "tags_json": contact.tags_json or [],
        "custom_fields_json": contact.custom_fields_json or {},
        "created_at": contact.created_at.isoformat() if contact.created_at else None,
        "updated_at": contact.updated_at.isoformat() if contact.updated_at else None,
    }


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


def _conversation_assigned_user_name(conversation: Conversation, assigned_users_by_id: dict | None = None) -> str | None:
    assigned_user_id = getattr(conversation, "assigned_user_id", None)
    stored_name = (getattr(conversation, "assigned_user_name", None) or "").strip()
    if stored_name:
        return stored_name
    if assigned_user_id and assigned_users_by_id:
        return assigned_users_by_id.get(assigned_user_id)
    return None


def _conversation_out(
    conversation: Conversation,
    *,
    last_message: str = "",
    assigned_users_by_id: dict | None = None,
) -> ConversationOut:
    phone = str(getattr(conversation, "phone", None) or conversation.phone_number or "").strip() or "desconhecido"
    contact = getattr(conversation, "contact", None)
    contact_name = getattr(contact, "name", None) if contact else None
    display_name = (contact_name or getattr(conversation, "name", None) or phone).strip() or phone
    stage = getattr(contact, "stage", None) if contact else None
    score = getattr(contact, "score", None) if contact else None

    return ConversationOut(
        id=conversation.id,
        tenant_id=conversation.tenant_id,
        contact_id=conversation.contact_id,
        phone=phone,
        name=display_name,
        avatar_url=conversation.avatar_url,
        stage=stage or "novo",
        score=int(score or 0),
        mode=conversation.mode or "bot",
        assigned_user_id=getattr(conversation, "assigned_user_id", None),
        assigned_user_name=_conversation_assigned_user_name(conversation, assigned_users_by_id),
        last_message=last_message or "",
        updated_at=conversation.updated_at or datetime.utcnow(),
    )


async def _publish_assignment_event(tenant_id, conversation: Conversation) -> None:
    conversation_payload = _conversation_out(conversation).model_dump(mode="json")
    payload = {
        "event": "conversation_assigned",
        "refresh": ["conversations"],
        "conversation_id": str(conversation.id),
        "phone": conversation.phone_number,
        "mode": conversation.mode,
        "assigned_user_id": str(conversation.assigned_user_id) if conversation.assigned_user_id else None,
        "assigned_user_name": conversation.assigned_user_name,
        "conversation": conversation_payload,
    }
    await publish_dashboard_event(tenant_id=tenant_id, payload=payload)
    await sse_broker.publish(f"{tenant_id}:{conversation.id}", payload)
    await sse_broker.publish(f"{tenant_id}:{conversation.phone_number}", payload)


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
                        Conversation.assigned_user_id,
                        Conversation.assigned_user_name,
                        Conversation.updated_at,
                    )
                )
                .where(Conversation.tenant_id == tenant.id)
                .order_by(desc(Conversation.updated_at), desc(Conversation.id))
            )
            .scalars()
            .all()
        )

        assigned_user_ids = {
            assigned_user_id
            for conversation in items
            if (assigned_user_id := getattr(conversation, "assigned_user_id", None))
        }
        assigned_users_by_id = (
            {
                user.id: user.full_name
                for user in db.execute(
                    select(TenantUser.id, TenantUser.full_name).where(
                        TenantUser.tenant_id == tenant.id,
                        TenantUser.id.in_(assigned_user_ids),
                    )
                ).all()
            }
            if assigned_user_ids
            else {}
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

            last_message = getattr(last_message_item, "text", "") if last_message_item else ""

            response.append(
                _conversation_out(
                    conversation,
                    last_message=last_message,
                    assigned_users_by_id=assigned_users_by_id,
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
            "[GET CONTACTS] tenant_id=%s contacts_found=%s",
            tenant.id,
            len(contacts),
        )
        logger.info(
            "[GET CONTACTS HEADERS] tenant_id=%s x_tenant_id=%s x_tenant_slug=%s",
            tenant.id,
            tenant.id,
            tenant.slug,
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

        for idx, contact in enumerate(contacts[:3]):
            print(f"[GET CONTACTS SAMPLE {idx}]", {
                "id": str(contact.id),
                "phone": contact.phone,
                "tenant_id": str(contact.tenant_id),
                "name": contact.name,
            })

        return {
            "success": True,
            "items": [
                {
                    "id": str(c.id),
                    "phone": c.phone,
                    "name": c.name,
                    "first_name": c.first_name,
                    "last_name": c.last_name,
                    "email": c.email,
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
    try:
        print("[SEND_MESSAGE STEP 1]")
        phone = normalize_phone(payload.phone)
        print("PHONE_NORMALIZED:", phone)
        message_text = sanitize_text(payload.message)
        if not phone or not message_text:
            raise HTTPException(status_code=400, detail="Dados inválidos")

        print("[SEND_MESSAGE STEP 2]")
        try:
            assert_tenant_can_send(tenant)
        except TenantLimitError as exc:
            raise HTTPException(status_code=403, detail=str(exc)) from exc
        print("[SEND_MESSAGE STEP 3]")

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
        print("[SEND_MESSAGE STEP 4]")

        if not contact:
            contact = upsert_contact_for_phone(
                db,
                tenant_id=tenant_id,
                phone=phone,
                name=payload.name,
            )
        print("[SEND_MESSAGE STEP 5]")

        conversation, _ = get_or_create_conversation(
            db=db,
            tenant_id=tenant_id,
            phone=phone,
            contact_id=contact.id if contact else None,
        )
        ensure_conversation_contact_link(conversation, contact)
        print("[SEND_MESSAGE STEP 6]")

        if contact and payload.name and payload.name.strip() and payload.name.strip() != contact.name:
            contact.name = payload.name.strip()
        if conversation.name is None and _looks_like_name(message_text):
            conversation.name = message_text.strip()
            if contact and (not contact.name or contact.name == "Cliente"):
                contact.name = conversation.name
        print("NOME CLIENTE:", conversation.name)
        print("[SEND_MESSAGE STEP 7]")

        print(f"[MODE CHECK] current mode={conversation.mode}")
        try:
            enqueue_send_message({"tenant_id": tenant.id, "phone": phone, "text": message_text})
        except Exception:
            pass
        print("[SEND_MESSAGE STEP 8]")

        print("SALVANDO_MSG:", phone, message_text)
        message = Message(
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            text=message_text,
            created_at=datetime.utcnow(),
            from_me=True,
        )
        print("[SEND_MESSAGE STEP 9]")
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
            register_contact_event(db, tenant_id=tenant.id, contact_id=contact.id, event_type="message_sent", title="Mensagem enviada", description=message_text, contact=contact)
        conversation.updated_at = datetime.utcnow()
        print("[SEND_MESSAGE STEP 10]")
        db.commit()
        print("[SEND_MESSAGE STEP 11]")
        db.refresh(message)
        print("[SEND_MESSAGE STEP 12]")

        message_payload = {"event": "message", "message": MessageOut.model_validate(message).model_dump(mode="json")}
        print("[WS BROADCAST] message", conversation.id)
        await sse_broker.publish(f"{tenant.id}:{phone}", message_payload)
        await sse_broker.publish(f"{tenant.id}:{conversation.id}", message_payload)
        display_name = (conversation.name or phone or "Contato").strip()
        print("[SEND_MESSAGE STEP 13]")
        await publish_dashboard_event(
            tenant_id=tenant.id,
            payload={
                "event": "dashboard_activity",
                "refresh": ["analytics", "conversations"],
                "activity": {
                    "id": str(message.id),
                    "type": "MESSAGE_SENT",
                    "title": display_name,
                    "description": message_text,
                    "entity_type": "conversation",
                    "entity_id": str(conversation.id),
                    "contact_name": conversation.name,
                    "phone": phone,
                    "created_at": message.created_at.isoformat(),
                },
            },
        )
        print("[SEND_MESSAGE STEP 14]")
        return message
    except Exception:
        logger.exception("[SEND_MESSAGE ERROR]")
        raise


@router.post("/send", response_model=MessageOut)
async def send_message_legacy(payload: SendMessageRequest, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    return await send_message(payload, tenant, db)


@router.post("/take-over/{phone}", response_model=ToggleAssignmentResponse)
async def take_over(
    phone: str,
    tenant: Tenant = Depends(get_current_tenant),
    current_user: TenantUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    sanitized_phone = normalize_phone(phone)
    print("PHONE_NORMALIZED:", sanitized_phone)
    conversation = db.execute(
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
                Conversation.assigned_user_id,
                Conversation.assigned_user_name,
                Conversation.updated_at,
            )
        )
        .where(Conversation.tenant_id == tenant.id, Conversation.phone_number == sanitized_phone)
    ).scalars().first()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    conversation.assigned_user_id = current_user.id
    conversation.assigned_user_name = current_user.full_name
    conversation.mode = "human"
    conversation.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(conversation)
    await _publish_assignment_event(tenant.id, conversation)

    conversation_out = _conversation_out(conversation)
    return ToggleAssignmentResponse(
        phone=sanitized_phone,
        status="human",
        conversation_id=conversation.id,
        mode=conversation.mode,
        assigned_user_id=conversation.assigned_user_id,
        assigned_user_name=conversation.assigned_user_name,
        conversation=conversation_out,
    )


@router.patch("/conversations/{conversation_id}/assign", response_model=ToggleAssignmentResponse)
async def assign_conversation(
    conversation_id: UUID,
    payload: ConversationAssignmentRequest,
    tenant: Tenant = Depends(get_current_tenant),
    current_user: TenantUser = Depends(get_current_user),
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
        raise HTTPException(status_code=404, detail="Conversa nÃ£o encontrada")

    if payload.user_id is None and payload.self is not True:
        conversation.assigned_user_id = None
        conversation.assigned_user_name = None
        conversation.mode = "bot"
    else:
        if payload.user_id is not None and payload.user_id != current_user.id:
            target_user = db.execute(
                select(TenantUser).where(
                    TenantUser.tenant_id == tenant.id,
                    TenantUser.id == payload.user_id,
                )
            ).scalars().first()
            if not target_user:
                raise HTTPException(status_code=404, detail="Atendente nÃ£o encontrado")
        else:
            target_user = current_user

        conversation.assigned_user_id = target_user.id
        conversation.assigned_user_name = target_user.full_name
        conversation.mode = "human"

    conversation.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(conversation)
    await _publish_assignment_event(tenant.id, conversation)

    conversation_out = _conversation_out(conversation)
    return ToggleAssignmentResponse(
        phone=conversation.phone_number,
        status=conversation.mode,
        conversation_id=conversation.id,
        mode=conversation.mode,
        assigned_user_id=conversation.assigned_user_id,
        assigned_user_name=conversation.assigned_user_name,
        conversation=conversation_out,
    )


@router.patch("/conversations/{conversation_id}/mode")
async def update_conversation_mode(
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

    logger.info(
        "[CONVERSATION MODE UPDATE] requested tenant_id=%s conversation_id=%s from_mode=%s to_mode=%s",
        tenant.id,
        conversation.id,
        conversation.mode,
        mode,
    )

    if mode == "bot":
        conversation.assigned_user_id = None
        conversation.assigned_user_name = None
        try:
            active_flow = get_active_visual_flow(db=db, tenant_id=tenant.id)
            logger.info(
                "[CONVERSATION MODE UPDATE] bot preflight completed tenant_id=%s conversation_id=%s active_flow_id=%s",
                tenant.id,
                conversation.id,
                getattr(active_flow, "id", None),
            )
        except HTTPException as exc:
            logger.warning(
                "[CONVERSATION MODE UPDATE] bot preflight failed tenant_id=%s conversation_id=%s detail=%s",
                tenant.id,
                conversation.id,
                exc.detail,
            )
            raise HTTPException(
                status_code=exc.status_code,
                detail="Nenhum fluxo publicado válido encontrado para este atendimento.",
            ) from exc

    conversation.mode = mode
    conversation.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(conversation)
    await publish_dashboard_event(
        tenant_id=tenant.id,
        payload={
            "event": "conversation_updated",
            "refresh": ["analytics", "conversations"],
            "activity": {
                "id": str(conversation.id),
                "type": "HUMAN_REQUEST" if mode == "human" else "CONVERSATION_MODE_UPDATED",
                "title": (conversation.name or conversation.phone_number or "Conversa"),
                "description": "Solicitação humana" if mode == "human" else f"Modo atualizado para {mode}",
                "entity_type": "conversation",
                "entity_id": str(conversation.id),
                "contact_name": conversation.name,
                "phone": conversation.phone_number,
                "created_at": datetime.utcnow().isoformat(),
            },
        },
    )
    await _publish_assignment_event(tenant.id, conversation)

    return {
        "status": "updated",
        "mode": mode,
        "assigned_user_id": conversation.assigned_user_id,
        "assigned_user_name": conversation.assigned_user_name,
    }


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


@router.websocket("/ws/messages/{conversation_id}")
async def ws_messages(
    websocket: WebSocket,
    conversation_id: UUID,
):
    print("[WS HANDSHAKE START MESSAGES]", conversation_id)
    tenant_id_raw = str(websocket.query_params.get("tenant_id") or "").strip()
    token = str(websocket.query_params.get("token") or "").strip()
    try:
        tenant_id = UUID(tenant_id_raw)
    except ValueError:
        print("[WS ERROR] Invalid tenant_id")
        await websocket.close(code=1008)
        return

    db = SessionLocal()
    try:
        user = authenticate_ws_user(db, tenant_id, token)
        conversation = (
            db.execute(
                select(Conversation).where(
                    Conversation.id == conversation_id,
                    Conversation.tenant_id == tenant_id,
                )
            )
            .scalars()
            .first()
        )
        if not conversation:
            print("[WS ERROR] Conversation not found")
            await websocket.close(code=1008)
            return

        participant_id = str(user.id)
        participant_name = user.full_name
        presence = PresenceService()

        async def handle_client_message(payload: dict, connection_id: str) -> None:
            event_type = str(payload.get("type") or "").strip()
            if event_type in {"heartbeat", "presence_heartbeat"}:
                presence.heartbeat(
                    tenant_id=tenant_id,
                    conversation_id=conversation.id,
                    participant_id=participant_id,
                )
                return

            if event_type == "typing_start":
                typing_payload = presence.typing_start(
                    tenant_id=tenant_id,
                    conversation_id=conversation.id,
                    participant_id=participant_id,
                    participant_type="agent",
                    participant_name=participant_name,
                )
                typing_payload["sender_connection_id"] = connection_id
                await presence.publish_typing_update(typing_payload)
                return

            if event_type == "typing_stop":
                typing_payload = presence.typing_stop(
                    tenant_id=tenant_id,
                    conversation_id=conversation.id,
                    participant_id=participant_id,
                    participant_type="agent",
                    participant_name=participant_name,
                )
                typing_payload["sender_connection_id"] = connection_id
                await presence.publish_typing_update(typing_payload)

        print("[WS CONNECTED MESSAGE]", conversation_id)
        channel = f"{tenant_id}:{conversation.id}"
        await websocket.accept()
        online_payload = presence.mark_online(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            participant_id=participant_id,
            participant_type="agent",
            participant_name=participant_name,
        )
        await presence.publish_presence_update(online_payload)
        try:
            await sse_broker.subscribe_websocket(channel, websocket, on_client_message=handle_client_message)
        finally:
            print("[WS DISCONNECT MESSAGE]", conversation_id)
            offline_payload = presence.mark_offline(
                tenant_id=tenant_id,
                conversation_id=conversation.id,
                participant_id=participant_id,
                participant_type="agent",
                participant_name=participant_name,
            )
            if offline_payload.get("status") == "offline":
                await presence.publish_presence_update(offline_payload)
            sse_broker.unsubscribe_websocket(channel, websocket)
    except Exception as e:
        print("[WS ERROR]", repr(e))
        raise
    finally:
        db.close()


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






@router.get("/crm/contacts/{contact_id}/events/stream")
async def stream_contact_events(
    contact_id: UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    contact = db.execute(
        select(Contact)
        .options(load_only(Contact.id))
        .where(Contact.id == contact_id, Contact.tenant_id == tenant.id)
    ).scalars().first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")

    channel = f"crm:{tenant.id}:{contact.id}"
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



@router.post("/contacts")
def create_contact(
    payload: dict,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    phone = normalize_phone(str(payload.get("phone") or ""))
    if not phone:
        raise HTTPException(status_code=400, detail="Telefone obrigatório")

    existing = db.execute(
        select(Contact).where(Contact.tenant_id == tenant.id, Contact.phone == phone)
    ).scalars().first()
    if existing:
        raise HTTPException(status_code=409, detail="Contato já existe para este telefone")

    tags = payload.get("tags_json") if isinstance(payload.get("tags_json"), list) else payload.get("tags")
    contact = Contact(
        tenant_id=tenant.id,
        phone=phone,
        name=str(payload.get("name") or "").strip() or None,
        first_name=str(payload.get("first_name") or "").strip() or None,
        last_name=str(payload.get("last_name") or "").strip() or None,
        email=str(payload.get("email") or "").strip() or None,
        source=str(payload.get("source") or "whatsapp").strip() or "whatsapp",
        tags_json=[str(tag).strip() for tag in tags if str(tag).strip()] if isinstance(tags, list) else [],
        custom_fields_json=payload.get("custom_fields_json") if isinstance(payload.get("custom_fields_json"), dict) else {},
    )
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return _serialize_contact_summary(contact)

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
        "phone": contact.phone,
        "source": contact.source,
        "first_name": contact.first_name,
        "last_name": contact.last_name,
        "email": contact.email,
        "tags_json": contact.tags_json or [],
        "custom_fields_json": contact.custom_fields_json or {},
    }


@router.put("/contacts/{contact_id}")
def replace_contact(
    contact_id: UUID,
    payload: dict,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    contact = db.execute(select(Contact).where(Contact.tenant_id == tenant.id, Contact.id == contact_id)).scalars().first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")

    phone = normalize_phone(str(payload.get("phone") or contact.phone or ""))
    if not phone:
        raise HTTPException(status_code=400, detail="Telefone obrigatório")

    duplicate = db.execute(
        select(Contact).where(Contact.tenant_id == tenant.id, Contact.phone == phone, Contact.id != contact.id)
    ).scalars().first()
    if duplicate:
        raise HTTPException(status_code=409, detail="Já existe outro contato com este telefone")

    tags = payload.get("tags_json") if isinstance(payload.get("tags_json"), list) else payload.get("tags")
    contact.phone = phone
    contact.name = str(payload.get("name") or "").strip() or None
    contact.first_name = str(payload.get("first_name") or "").strip() or None
    contact.last_name = str(payload.get("last_name") or "").strip() or None
    contact.email = str(payload.get("email") or "").strip() or None
    contact.source = str(payload.get("source") or "whatsapp").strip() or "whatsapp"
    contact.tags_json = [str(tag).strip() for tag in tags if str(tag).strip()] if isinstance(tags, list) else []
    contact.custom_fields_json = payload.get("custom_fields_json") if isinstance(payload.get("custom_fields_json"), dict) else {}
    contact.updated_at = datetime.utcnow()
    db.add(contact)
    db.commit()
    db.refresh(contact)
    return _serialize_contact_summary(contact)


@router.delete("/contacts/{contact_id}")
def delete_contact(
    contact_id: UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    contact = db.execute(select(Contact).where(Contact.tenant_id == tenant.id, Contact.id == contact_id)).scalars().first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")
    db.delete(contact)
    db.commit()
    return {"deleted": True}

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


@router.get("/contacts/{contact_id}")
def get_contact_profile(contact_id: UUID, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    contact = db.execute(select(Contact).where(Contact.tenant_id == tenant.id, Contact.id == contact_id)).scalars().first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")
    messages_count = db.execute(select(func.count(ContactEvent.id)).where(ContactEvent.tenant_id == tenant.id, ContactEvent.contact_id == contact.id, ContactEvent.type.in_(["message_received", "message_sent"]))).scalar() or 0
    campaigns_received = db.execute(select(func.count(ContactEvent.id)).where(ContactEvent.tenant_id == tenant.id, ContactEvent.contact_id == contact.id, ContactEvent.type.in_(["campaign_sent", "campaign_received"]))).scalar() or 0
    flows_executed = db.execute(select(func.count(ContactEvent.id)).where(ContactEvent.tenant_id == tenant.id, ContactEvent.contact_id == contact.id, ContactEvent.type.in_(["flow_started", "flow_completed", "flow_finished"]))).scalar() or 0
    inbound_count = db.execute(select(func.count(ContactEvent.id)).where(ContactEvent.tenant_id == tenant.id, ContactEvent.contact_id == contact.id, ContactEvent.type == "message_received")).scalar() or 0
    outbound_count = db.execute(select(func.count(ContactEvent.id)).where(ContactEvent.tenant_id == tenant.id, ContactEvent.contact_id == contact.id, ContactEvent.type == "message_sent")).scalar() or 0
    response_rate = int(round((inbound_count / outbound_count) * 100)) if outbound_count else 0
    return {"contact": {"id": str(contact.id), "tenant_id": str(contact.tenant_id), "name": contact.name, "phone": contact.phone, "avatar_url": contact.avatar_url, "tags_json": contact.tags_json or [], "score": contact.score or 0, "lifecycle_stage": contact.lifecycle_stage, "source": contact.source, "last_interaction_at": contact.last_interaction_at.isoformat() if contact.last_interaction_at else None, "custom_fields_json": contact.custom_fields_json or {}, "notes": contact.notes, "campaigns_received": campaigns_received, "flows_executed": flows_executed, "messages_count": messages_count, "response_rate": response_rate}}

@router.get("/contacts/{contact_id}/events")
def get_contact_events(contact_id: UUID, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    events = db.execute(select(ContactEvent).where(ContactEvent.tenant_id == tenant.id, ContactEvent.contact_id == contact_id).order_by(desc(ContactEvent.created_at))).scalars().all()
    return {"items": [{"id": str(e.id), "type": e.type, "title": e.title, "description": e.description, "metadata_json": e.metadata_json or {}, "created_at": e.created_at.isoformat()} for e in events]}

@router.post("/contacts/{contact_id}/notes")
def add_contact_note(contact_id: UUID, payload: dict, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    contact = db.execute(select(Contact).where(Contact.tenant_id == tenant.id, Contact.id == contact_id)).scalars().first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")
    note = str(payload.get("note") or "").strip()
    if not note:
        raise HTTPException(status_code=400, detail="Nota obrigatória")
    contact.notes = ((contact.notes or "") + "\n" + note).strip()
    register_contact_event(db, tenant_id=tenant.id, contact_id=contact.id, event_type="note_added", title="Nota adicionada", description=note, contact=contact)
    db.commit()
    return {"ok": True}

@router.post("/contacts/{contact_id}/tags")
def add_contact_tag(contact_id: UUID, payload: dict, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    contact = db.execute(select(Contact).where(Contact.tenant_id == tenant.id, Contact.id == contact_id)).scalars().first()
    if not contact:
        raise HTTPException(status_code=404, detail="Contato não encontrado")
    tag = str(payload.get("tag") or "").strip()
    if not tag:
        raise HTTPException(status_code=400, detail="Tag obrigatória")
    tags = list(contact.tags_json or [])
    if tag not in tags:
        tags.append(tag)
    contact.tags_json = tags
    register_contact_event(db, tenant_id=tenant.id, contact_id=contact.id, event_type="tag_added", title="Tag adicionada", description=tag, contact=contact)
    db.commit()
    return {"ok": True, "tags_json": tags}
