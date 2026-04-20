from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, load_only

from app.database import get_db
from app.models import Conversation, Message
from app.schemas.chat import MessageOut
from app.services.contact_sync_service import ensure_conversation_contact_link, upsert_contact_for_phone
from app.services.conversation_service import get_or_create_conversation
from app.services.message_router import handle_incoming_message
from app.services.realtime_service import sse_broker
from app.models import Tenant
from app.services.tenant_service import get_or_create_default_tenant
from app.utils.phone import normalize_phone

router = APIRouter()

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

        tenant_slug = (request.headers.get("x-tenant-slug") or "").strip()

        for incoming in messages_data:
            phone = incoming["phone"]
            normalized_phone = normalize_phone(phone)
            print("PHONE_NORMALIZED:", normalized_phone)
            incoming_message = incoming["text"]
            contact_name = incoming.get("name")
            phone_number_id = incoming.get("phone_number_id")

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
            print("TENANT ID:", tenant.id, type(tenant.id))


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
                print(f"Conversa encontrada: {conversation.id}")
            else:
                print(f"Nenhuma conversa encontrada, criando nova para {normalized_phone}")

            if contact_name and not conversation.name:
                conversation.name = contact_name
            ensure_conversation_contact_link(conversation, contact)

            if conversation.name is None and _looks_like_name(incoming_message):
                conversation.name = incoming_message.strip()
            if conversation.name and (not contact.name or contact.name == "Cliente"):
                contact.name = conversation.name
            print("NOME CLIENTE:", conversation.name)

            contact.last_message_at = datetime.utcnow()

            print("SALVANDO_MSG:", normalized_phone, incoming_message)
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
            print("CONVERSA_ID:", conversation.id)
            print("MSG_SALVA:", inbound_message.text)

            handle_incoming_message(db, inbound_message, conversation)

            print(f"Evento processado (telefone={normalized_phone}, conteúdo={incoming_message})")

        db.commit()
    except Exception as e:
        db.rollback()
        print("Erro ao processar webhook:", str(e))

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
