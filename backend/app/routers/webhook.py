import json
import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models import Conversation, Message
from backend.app.services.ai_service import generate_ai_response
from backend.app.services.message_service import extract_whatsapp_messages
from backend.app.services.realtime_service import sse_broker
from backend.app.services.whatsapp_service import send_whatsapp_message

logger = logging.getLogger(__name__)

router = APIRouter(tags=["webhook"])


@router.get("/webhook")
async def verify(request: Request):
    verify_token = os.getenv("VERIFY_TOKEN")

    mode = request.query_params.get("hub.mode")
    token = request.query_params.get("hub.verify_token")
    challenge = request.query_params.get("hub.challenge")

    if mode == "subscribe" and token == verify_token and challenge:
        return int(challenge)

    raise HTTPException(status_code=403, detail="verification failed")


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    payload = await request.json()
    logger.info("📩 Evento recebido do WhatsApp: %s", json.dumps(payload, ensure_ascii=False))

    inbound_messages = extract_whatsapp_messages(payload)

    for inbound in inbound_messages:
        phone = inbound["phone"]
        text = inbound["text"]
        name = inbound["name"]

        conversation = db.execute(select(Conversation).where(Conversation.phone == phone)).scalar_one_or_none()
        if not conversation:
            conversation = Conversation(phone=phone, name=name, assigned_to="IA")
            db.add(conversation)

        message = Message(phone=phone, content=text, from_me=False)
        db.add(message)
        conversation.last_message = text
        if name:
            conversation.name = name
        db.commit()
        db.refresh(message)

        await sse_broker.publish(
            phone,
            {"event": "message", "message": {"id": message.id, "phone": message.phone, "content": message.content, "from_me": message.from_me, "timestamp": message.timestamp.isoformat()}},
        )

        if conversation.assigned_to == "IA":
            response = generate_ai_response(text)
            send_whatsapp_message(phone, response)

            ai_message = Message(phone=phone, content=response, from_me=True)
            db.add(ai_message)
            conversation.last_message = response
            db.commit()
            db.refresh(ai_message)

            await sse_broker.publish(
                phone,
                {"event": "message", "message": {"id": ai_message.id, "phone": ai_message.phone, "content": ai_message.content, "from_me": ai_message.from_me, "timestamp": ai_message.timestamp.isoformat()}},
            )

    return {"status": "received"}
