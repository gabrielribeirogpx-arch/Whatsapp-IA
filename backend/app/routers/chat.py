import asyncio
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models import Conversation, Message
from backend.app.schemas.chat import (
    ConversationOut,
    MessageOut,
    SendMessageRequest,
    ToggleAssignmentResponse,
)
from backend.app.services.message_service import sanitize_phone, sanitize_text
from backend.app.services.realtime_service import sse_broker
from backend.app.services.whatsapp_service import send_whatsapp_message

router = APIRouter(prefix="/api", tags=["chat"])


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db)):
    items = db.execute(select(Conversation).order_by(desc(Conversation.id))).scalars().all()
    return items


@router.get("/messages/{phone}", response_model=list[MessageOut])
def get_messages(phone: str, db: Session = Depends(get_db)):
    sanitized_phone = sanitize_phone(phone)
    items = (
        db.execute(
            select(Message)
            .where(Message.phone == sanitized_phone)
            .order_by(Message.timestamp.asc(), Message.id.asc())
        )
        .scalars()
        .all()
    )
    return items


@router.post("/send", response_model=MessageOut)
async def send_message(payload: SendMessageRequest, db: Session = Depends(get_db)):
    phone = sanitize_phone(payload.phone)
    message_text = sanitize_text(payload.message)
    if not phone or not message_text:
        raise HTTPException(status_code=400, detail="Dados inválidos")

    conversation = db.execute(select(Conversation).where(Conversation.phone == phone)).scalar_one_or_none()
    if not conversation:
        conversation = Conversation(phone=phone, name=sanitize_text(payload.name or "Cliente"))
        db.add(conversation)

    send_whatsapp_message(phone, message_text)

    message = Message(phone=phone, content=message_text, from_me=True, timestamp=datetime.utcnow())
    db.add(message)
    conversation.last_message = message_text
    db.commit()
    db.refresh(message)

    await sse_broker.publish(phone, {"event": "message", "message": MessageOut.model_validate(message).model_dump(mode="json")})
    return message


@router.post("/take-over/{phone}", response_model=ToggleAssignmentResponse)
def take_over(phone: str, db: Session = Depends(get_db)):
    sanitized_phone = sanitize_phone(phone)
    conversation = db.execute(select(Conversation).where(Conversation.phone == sanitized_phone)).scalar_one_or_none()
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversa não encontrada")

    conversation.assigned_to = "HUMANO" if conversation.assigned_to == "IA" else "IA"
    db.commit()

    return ToggleAssignmentResponse(phone=sanitized_phone, assigned_to=conversation.assigned_to)


@router.get("/stream/messages/{phone}")
async def stream_messages(phone: str):
    sanitized_phone = sanitize_phone(phone)
    queue = await sse_broker.subscribe(sanitized_phone)

    async def event_generator():
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=20)
                    yield data
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            sse_broker.unsubscribe(sanitized_phone, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")
