from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from backend.app.database import SessionLocal, get_db
from backend.app.models import Conversation, Message
from backend.app.services.conversation_service import save_conversation
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

        messages_data = []
        entry = payload.get("entry", [])

        for e in entry:
            changes = e.get("changes", [])

            for change in changes:
                value = change.get("value", {})
                contacts = value.get("contacts", [])
                contact_name = (contacts[0].get("profile", {}).get("name") if contacts else None)
                phone_number_id = value.get("metadata", {}).get("phone_number_id")

                messages = value.get("messages", [])

                for msg in messages:
                    from_number = msg.get("from")
                    text_body = msg.get("text", {}).get("body")

                    print(f"Mensagem recebida de {from_number}: {text_body}")

                    if text_body:
                        messages_data.append(
                            {
                                "phone": from_number,
                                "text": text_body,
                                "phone_number_id": phone_number_id,
                                "name": contact_name,
                                "message_id": msg.get("id"),
                            }
                        )

        if not messages_data:
            print("Evento ignorado: payload sem mensagens de texto")
            return {"status": "ignored"}

        for incoming in messages_data:
            phone = incoming["phone"]
            incoming_message = incoming["text"]
            phone_number_id = incoming.get("phone_number_id")
            tenant = resolve_tenant_by_phone_number_id(db, phone_number_id) or get_or_create_default_tenant(db)

            conversation = db.execute(select(Conversation).where(Conversation.phone_number == phone)).scalar_one_or_none()
            if not conversation:
                conversation = Conversation(phone_number=phone, message=incoming_message)
                db.add(conversation)
                db.flush()
            else:
                conversation.message = incoming_message

            db.add(
                Message(
                    conversation_id=conversation.id,
                    text=incoming_message,
                    from_me=False,
                    created_at=datetime.utcnow(),
                )
            )

            auto_reply = "🔥 Olá! Aqui é a IA. Como posso te ajudar?"
            enviar_mensagem(
                phone,
                auto_reply,
                token=tenant.whatsapp_token,
                phone_number_id=tenant.phone_number_id,
            )

            db.add(
                Message(
                    conversation_id=conversation.id,
                    text=auto_reply,
                    from_me=True,
                    created_at=datetime.utcnow(),
                )
            )

            print(f"Evento processado (telefone={phone}, conteúdo={incoming_message})")
            print(f"Resposta automática enviada para {phone}")

            persistence_db = SessionLocal()
            try:
                save_conversation(
                    db=persistence_db,
                    phone=phone,
                    message=incoming_message,
                    response=auto_reply,
                )
            except Exception as persistence_error:
                persistence_db.rollback()
                print("Falha ao persistir conversa:", str(persistence_error))
            finally:
                persistence_db.close()

        db.commit()
    except Exception as e:
        db.rollback()
        print("Erro ao processar webhook:", str(e))

    return {"status": "message processed"}


@router.get("/conversations")
def list_conversations(db: Session = Depends(get_db)):
    conversations = db.execute(select(Conversation).order_by(desc(Conversation.created_at), desc(Conversation.id))).scalars().all()

    response: list[dict[str, str | None]] = []
    for conversation in conversations:
        last_message = db.execute(
            select(Message)
            .where(Message.conversation_id == conversation.id)
            .order_by(desc(Message.created_at), desc(Message.id))
            .limit(1)
        ).scalar_one_or_none()
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
