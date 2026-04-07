from datetime import datetime

from fastapi import APIRouter, Depends, Request
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.database import get_db
from backend.app.models import Conversation, Message
from backend.app.services.message_service import extract_whatsapp_messages
from backend.app.services.tenant_service import get_or_create_default_tenant, resolve_tenant_by_phone_number_id
from backend.app.services.whatsapp_service import enviar_mensagem

router = APIRouter()


@router.get("/webhook")
async def verify():
    return {"status": "webhook ativo"}


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    try:
        payload = await request.json()
        print("Payload recebido:", payload)

        messages_data = extract_whatsapp_messages(payload)
        if not messages_data:
            print("Evento ignorado: payload sem 'entry'")
            return {"status": "ignored"}

        for incoming in messages_data:
            phone = incoming["phone"]
            incoming_message = incoming["text"]
            phone_number_id = incoming.get("phone_number_id")
            tenant = resolve_tenant_by_phone_number_id(db, phone_number_id) or get_or_create_default_tenant(db)

            conversation = db.execute(
                select(Conversation).where(Conversation.tenant_id == tenant.id, Conversation.phone == phone)
            ).scalar_one_or_none()
            if not conversation:
                conversation = Conversation(
                    tenant_id=tenant.id,
                    phone=phone,
                    name=incoming.get("name") or "Cliente",
                    status="bot",
                )
                db.add(conversation)
                db.flush()

            inbound = Message(
                tenant_id=tenant.id,
                phone=phone,
                conversation_id=conversation.id,
                whatsapp_message_id=incoming.get("message_id"),
                role="user",
                message=incoming_message,
                content=incoming_message,
                from_me=False,
                created_at=datetime.utcnow(),
                timestamp=datetime.utcnow(),
            )
            db.add(inbound)

            auto_reply = "🔥 Olá! Aqui é a IA. Como posso te ajudar?"
            enviar_mensagem(
                phone,
                auto_reply,
                token=tenant.whatsapp_token,
                phone_number_id=tenant.phone_number_id,
            )

            outbound = Message(
                tenant_id=tenant.id,
                phone=phone,
                conversation_id=conversation.id,
                role="assistant",
                message=auto_reply,
                content=auto_reply,
                from_me=True,
                created_at=datetime.utcnow(),
                timestamp=datetime.utcnow(),
            )
            db.add(outbound)

            conversation.last_message = auto_reply
            conversation.updated_at = datetime.utcnow()

            print(f"Evento processado (telefone={phone}, conteúdo={incoming_message})")
            print(f"Resposta automática enviada para {phone}")

        db.commit()
    except Exception as e:
        db.rollback()
        print("Erro ao processar webhook:", str(e))

    return {"status": "message processed"}


@router.get("/conversations")
def list_conversations(db: Session = Depends(get_db)):
    conversations = db.execute(
        select(Conversation).order_by(desc(Conversation.updated_at), desc(Conversation.id))
    ).scalars().all()

    response: list[dict[str, str | int | None]] = []
    for conversation in conversations:
        last_message = db.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(desc(Message.timestamp), desc(Message.id))
            .limit(1)
        ).scalar_one_or_none()
        response.append(
            {
                "conversation_id": conversation.id,
                "phone_number": conversation.phone,
                "created_at": conversation.created_at.isoformat(),
                "last_message": (last_message.content if last_message else None),
            }
        )
    return response


@router.get("/messages/{conversation_id}")
def list_messages(conversation_id: int, db: Session = Depends(get_db)):
    messages = db.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.timestamp.asc(), Message.id.asc())
    ).scalars().all()

    return [
        {
            "id": item.id,
            "conversation_id": item.conversation_id,
            "from_me": item.from_me,
            "text": item.content,
            "created_at": (item.created_at or item.timestamp).isoformat(),
        }
        for item in messages
    ]
