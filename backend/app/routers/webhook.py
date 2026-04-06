import json
import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.database import get_db
from backend.app.models import AIConfig, Conversation, Message
from backend.app.services.ai_service import gerar_resposta
from backend.app.services.context_service import build_context
from backend.app.services.message_service import extract_whatsapp_messages
from backend.app.services.realtime_service import sse_broker
from backend.app.services.tenant_service import (
    TenantLimitError,
    assert_tenant_can_send,
    consume_usage,
    get_or_create_default_tenant,
    get_tenant_by_phone_number_id,
)
from backend.app.services.whatsapp_service import WhatsAppConfigError, send_message

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhook"])


def _channel(tenant_id: int, phone: str) -> str:
    return f"{tenant_id}:{phone}"


@router.get("/webhook")
async def verify(request: Request):
    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == settings.verify_token and challenge:
        return int(challenge)

    raise HTTPException(status_code=403, detail="verification failed")


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    logger.info("📩 Evento recebido do WhatsApp: %s", json.dumps(payload, ensure_ascii=False))

    if any(change.get("value", {}).get("statuses") for entry in payload.get("entry", []) for change in entry.get("changes", [])):
        return {"status": "ignored_status_event"}

    inbound_messages = extract_whatsapp_messages(payload)

    for inbound in inbound_messages:
        phone = inbound["phone"]
        text = inbound["text"]
        name = inbound["name"]
        message_id = inbound.get("message_id")
        phone_number_id = inbound.get("phone_number_id")

        tenant = get_tenant_by_phone_number_id(db, phone_number_id) or get_or_create_default_tenant(db)

        if message_id:
            already_processed = db.execute(select(Message).where(Message.whatsapp_message_id == message_id)).scalar_one_or_none()
            if already_processed:
                logger.info("Mensagem duplicada ignorada. message_id=%s", message_id)
                continue

        conversation = db.execute(
            select(Conversation).where(Conversation.tenant_id == tenant.id, Conversation.phone == phone)
        ).scalar_one_or_none()
        if not conversation:
            conversation = Conversation(tenant_id=tenant.id, phone=phone, name=name, status="bot")
            db.add(conversation)
            db.flush()

        message = Message(
            tenant_id=tenant.id,
            phone=phone,
            conversation_id=conversation.id,
            whatsapp_message_id=message_id,
            role="user",
            message=text,
            created_at=datetime.utcnow(),
            content=text,
            from_me=False,
        )
        db.add(message)
        conversation.last_message = text
        conversation.updated_at = datetime.utcnow()
        if name:
            conversation.name = name
        db.commit()
        db.refresh(message)

        await sse_broker.publish(
            _channel(tenant.id, phone),
            {
                "event": "message",
                "message": {
                    "id": message.id,
                    "tenant_id": tenant.id,
                    "phone": message.phone,
                    "content": message.content,
                    "from_me": message.from_me,
                    "timestamp": message.timestamp.isoformat(),
                },
            },
        )

        if conversation.status == "bot":
            try:
                assert_tenant_can_send(tenant)
            except TenantLimitError:
                logger.warning("Tenant %s bloqueado/sem limite. IA não responderá.", tenant.slug)
                db.commit()
                continue

            context = build_context(db, tenant.id, phone)
            ai_config = db.execute(select(AIConfig).where(AIConfig.tenant_id == tenant.id)).scalar_one_or_none()
            response = gerar_resposta(context, text, ai_config)
            try:
                send_message(tenant.whatsapp_token or "", tenant.phone_number_id, phone, response)
            except WhatsAppConfigError:
                logger.warning("WhatsApp não configurado para tenant=%s. Resposta IA salva sem envio externo.", tenant.slug)

            ai_message = Message(
                tenant_id=tenant.id,
                phone=phone,
                conversation_id=conversation.id,
                role="assistant",
                message=response,
                created_at=datetime.utcnow(),
                content=response,
                from_me=True,
            )
            db.add(ai_message)
            consume_usage(tenant, 1)
            conversation.last_message = response
            conversation.updated_at = datetime.utcnow()
            db.commit()
            db.refresh(ai_message)

            await sse_broker.publish(
                _channel(tenant.id, phone),
                {
                    "event": "message",
                    "message": {
                        "id": ai_message.id,
                        "tenant_id": tenant.id,
                        "phone": ai_message.phone,
                        "content": ai_message.content,
                        "from_me": ai_message.from_me,
                        "timestamp": ai_message.timestamp.isoformat(),
                    },
                },
            )

    return {"status": "received"}
