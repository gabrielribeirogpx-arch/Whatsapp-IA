import json
import logging
import os
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.core.config import settings
from backend.app.database import get_db
from backend.app.models import Conversation, Message
from backend.app.services.message_service import extract_whatsapp_messages
from backend.app.services.realtime_service import sse_broker
from backend.app.services.tenant_service import (
    get_or_create_default_tenant,
    get_tenant_by_phone_number_id,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhook"])


def _channel(tenant_id: int, phone: str) -> str:
    return f"{tenant_id}:{phone}"


def generate_response(text: str) -> str:
    return f"Recebi sua mensagem: {text}. Em breve um atendente irá falar com você."


def send_whatsapp_message(to: str, message: str):
    url = f"https://graph.facebook.com/v18.0/{os.getenv('ID_DO_NUMERO_DE_TELEFONE')}/messages"

    headers = {
        "Authorization": f"Bearer {os.getenv('WHATSAPP_TOKEN')}",
        "Content-Type": "application/json",
    }

    data = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": message},
    }

    requests.post(url, headers=headers, json=data, timeout=15)


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

        auto_response = generate_response(text)
        try:
            send_whatsapp_message(phone, auto_response)
        except requests.RequestException as exc:
            logger.warning("Falha ao enviar mensagem WhatsApp para %s: %s", phone, exc)

        ai_message = Message(
            tenant_id=tenant.id,
            phone=phone,
            conversation_id=conversation.id,
            role="assistant",
            message=auto_response,
            created_at=datetime.utcnow(),
            content=auto_response,
            from_me=True,
        )
        db.add(ai_message)
        conversation.last_message = auto_response
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
