from datetime import datetime
import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, load_only

from app.database import get_db
from app.models import Conversation, Message
from app.schemas.chat import MessageOut
from app.services.contact_sync_service import ensure_conversation_contact_link, upsert_contact_for_phone
from app.services.conversation_service import get_or_create_conversation
from app.services.message_router import handle_incoming_message
from app.services.idempotency_service import register_processed_message
from app.services.message_service import normalize_meta_message
from app.services.realtime_service import sse_broker
from app.models import Tenant
from app.services.tenant_service import get_or_create_default_tenant
from app.utils.phone import normalize_phone

router = APIRouter()
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


@router.get("/webhook")
async def verify(
    hub_mode: str = Query(default="", alias="hub.mode"),
    hub_verify_token: str = Query(default="", alias="hub.verify_token"),
    hub_challenge: str = Query(default="", alias="hub.challenge"),
    db: Session = Depends(get_db),
):
    if hub_mode != "subscribe":
        raise HTTPException(status_code=400, detail="hub.mode inválido")

    tenant = None
    if hub_verify_token:
        tenant = db.execute(select(Tenant).where(Tenant.verify_token == hub_verify_token)).scalars().first()
    if not tenant:
        raise HTTPException(status_code=403, detail="verify_token ausente")
    return Response(content=hub_challenge, media_type="text/plain")


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
        logger.info("Webhook Meta recebido: keys=%s", list(payload.keys()))
        messages_data = normalize_meta_message(payload)

        if not messages_data:
            logger.info("Evento ignorado: payload sem mensagens processáveis")
            return {"status": "ignored"}

        tenant_slug = (request.headers.get("x-tenant-slug") or "").strip()

        for incoming in messages_data:
            phone = incoming["phone"]
            normalized_phone = normalize_phone(phone)
            incoming_message = incoming.get("text") or ""
            incoming_type = incoming.get("type") or "unknown"
            logger.info("[WEBHOOK DEBUG] type=%s message=%s", incoming_type, incoming_message)
            contact_name = incoming.get("name")
            phone_number_id = incoming.get("phone_number_id")
            logger.info(
                "Mensagem normalizada recebida phone=%s type=%s phone_number_id=%s",
                normalized_phone,
                incoming_type,
                phone_number_id,
            )

            tenant = None
            if tenant_slug:
                tenant = db.execute(select(Tenant).where(Tenant.slug == tenant_slug)).scalars().first()
            if not tenant:
                tenant = (
                    db.query(Tenant)
                    .filter(Tenant.phone_number_id == phone_number_id)
                    .first()
                    or get_or_create_default_tenant(db)
                )

            tenant_id = tenant.id
            incoming["tenant_id"] = str(tenant_id)
            logger.info("Tenant resolvido tenant_id=%s slug=%s", tenant.id, tenant.slug)
            message_id = (incoming.get("message_id") or "").strip()
            was_inserted = register_processed_message(db=db, tenant_id=tenant_id, message_id=message_id)
            if not was_inserted:
                logger.info("Mensagem duplicada ignorada tenant_id=%s phone=%s message_id=%s", tenant_id, normalized_phone, message_id)
                return {"status": "duplicate", "message_id": message_id}

            if incoming_type not in {"text", "interactive"} or not incoming_message:
                logger.info("Evento ignorado: tipo=%s sem texto processável", incoming_type)
                continue


            contact = upsert_contact_for_phone(
                db,
                tenant_id=tenant_id,
                phone=normalized_phone,
                name=contact_name,
            )

            conversation = (
                db.query(Conversation)
                .filter(
                    Conversation.tenant_id == tenant.id,
                    Conversation.phone_number == normalized_phone
                )
                .order_by(Conversation.updated_at.desc())
                .first()
            )
            existed = conversation is not None

            if not conversation:
                conversation, existed = get_or_create_conversation(
                    db=db,
                    tenant_id=tenant_id,
                    phone=normalized_phone,
                    contact_id=contact.id,
                )

            if existed:
                logger.info("Conversa encontrada id=%s", conversation.id)
            else:
                logger.info("Nenhuma conversa encontrada, criando nova para %s", normalized_phone)

            if contact_name and not conversation.name:
                conversation.name = contact_name
            ensure_conversation_contact_link(conversation, contact)

            if conversation.name is None and _looks_like_name(incoming_message):
                conversation.name = incoming_message.strip()
            if conversation.name and (not contact.name or contact.name == "Cliente"):
                contact.name = conversation.name
            contact.last_message_at = datetime.utcnow()

            logger.info("Salvando mensagem de entrada phone=%s conversation_id=%s", normalized_phone, conversation.id)
            inbound_message = Message(
                tenant_id=conversation.tenant_id,
                conversation_id=conversation.id,
                text=incoming_message,
                from_me=False,
                created_at=datetime.utcnow(),
            )
            db.add(inbound_message)
            db.commit()
            db.refresh(inbound_message)
            message_payload = {
                "event": "message",
                "message": MessageOut.model_validate(inbound_message).model_dump(mode="json"),
            }
            await sse_broker.publish(f"{tenant.id}:{normalized_phone}", message_payload)
            await sse_broker.publish(f"{tenant.id}:{conversation.id}", message_payload)

            handle_incoming_message(db, inbound_message, conversation)

            logger.info("Evento processado telefone=%s conteúdo=%s", normalized_phone, incoming_message)

        db.commit()
    except Exception as e:
        db.rollback()
        logger.exception("Erro ao processar webhook: %s", str(e))

    return {"status": "message processed"}


@router.get("/conversations")
def list_conversations(db: Session = Depends(get_db)):
    conversations = db.execute(
        select(Conversation)
        .options(load_only(Conversation.id, Conversation.phone_number, Conversation.created_at))
        .order_by(desc(Conversation.updated_at), desc(Conversation.id))
    ).scalars().all()

    response: list[dict[str, str | None]] = []
    for conversation in conversations:
        last_message = db.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(desc(Message.created_at), desc(Message.id))
            .limit(1)
        ).scalars().first()
        response.append(
            {
                "id": str(conversation.id),
                "phone_number": conversation.phone_number,
                "last_message": (last_message.text if last_message else None),
            }
        )
    return response


@router.get("/messages/{conversation_id}")
def list_messages(conversation_id: UUID, db: Session = Depends(get_db)):
    messages = db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc(), Message.id.asc())
    ).scalars().all()

    return [
        {
            "id": str(item.id),
            "conversation_id": str(item.conversation_id),
            "from_me": item.from_me,
            "text": item.text,
            "created_at": item.created_at.isoformat(),
        }
        for item in messages
    ]
