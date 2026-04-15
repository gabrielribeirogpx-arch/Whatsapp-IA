from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, load_only

from backend.app.database import SessionLocal, get_db
from backend.app.models import Conversation, Message
from backend.app.services.ai_provider import classificar_lead
from backend.app.services.ai_service import generate_ai_response
from backend.app.services.conversation_service import save_conversation
from backend.app.models import Tenant
from backend.app.services.tenant_service import get_or_create_default_tenant, resolve_tenant_by_phone_number_id
from backend.app.services.whatsapp_service import enviar_mensagem

router = APIRouter()

ATENDENTE_PROMPT = """Você é um atendente profissional via WhatsApp.

Seu objetivo é:
- Ajudar o cliente
- Responder dúvidas
- Ser claro e educado

REGRAS:
- Não force venda
- Seja direto
- Seja útil"""

VENDEDOR_PROMPT = """Você é um especialista em vendas via WhatsApp.

Cliente disse:
"{incoming_message}"

Histórico:
{history}

Nível do cliente:
{lead_level}

OBJETIVO:
Converter o cliente.

ESTRATÉGIA:

Se FRIO:
- Seja leve
- Gere curiosidade
- Faça perguntas simples

Se MORNO:
- Explore necessidade
- Mostre valor
- Direcione

Se QUENTE:
- Seja direto
- Crie urgência
- Leve para ação (compra/agendamento)

REGRAS:
- Nunca seja genérico
- Sempre faça pergunta
- Seja curto (WhatsApp)
- Pareça humano"""


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
            incoming_message = incoming["text"]
            phone_number_id = incoming.get("phone_number_id")

            tenant = None
            if tenant_slug:
                tenant = db.execute(select(Tenant).where(Tenant.slug == tenant_slug)).scalar_one_or_none()
            if not tenant:
                tenant = resolve_tenant_by_phone_number_id(db, phone_number_id) or get_or_create_default_tenant(db)

            ai_mode = tenant.ai_mode if tenant.ai_mode in {"atendente", "vendedor"} else "atendente"

            conversation = db.execute(
                select(Conversation)
                .options(load_only(Conversation.id, Conversation.phone_number, Conversation.message, Conversation.created_at))
                .where(Conversation.phone_number == phone)
                .order_by(desc(Conversation.created_at), desc(Conversation.id))
            ).scalars().first()
            if not conversation:
                print(f"Nenhuma conversa encontrada, criando nova para {phone}")
                conversation = Conversation(phone_number=phone, message=incoming_message)
                db.add(conversation)
                db.flush()
            else:
                print(f"Conversa encontrada: {conversation.id}")
                conversation.message = incoming_message

            db.add(
                Message(
                    conversation_id=conversation.id,
                    text=incoming_message,
                    from_me=False,
                    created_at=datetime.utcnow(),
                )
            )

            recent_messages = db.execute(
                select(Message)
                .where(Message.conversation_id == conversation.id)
                .order_by(desc(Message.created_at), desc(Message.id))
                .limit(10)
            ).scalars().all()

            history = ""
            for msg in reversed(recent_messages):
                role = "Cliente" if not msg.from_me else "Atendente"
                history += f"{role}: {msg.text}\n"

            if ai_mode == "vendedor":
                lead_level = classificar_lead(incoming_message)
                prompt = VENDEDOR_PROMPT.format(
                    incoming_message=incoming_message,
                    history=history,
                    lead_level=lead_level.upper(),
                )
            else:
                prompt = f"""
{ATENDENTE_PROMPT}

Histórico:
{history}

Cliente disse:
"{incoming_message}"
"""

            try:
                auto_reply = await generate_ai_response(prompt)
            except Exception as e:
                print(f"Erro IA: {e}")
                auto_reply = "Desculpa, tive um erro aqui. Pode repetir?"

            print(f"IA respondeu: {auto_reply}")
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
    conversations = db.execute(
        select(Conversation)
        .options(load_only(Conversation.id, Conversation.phone_number, Conversation.created_at))
        .order_by(desc(Conversation.created_at), desc(Conversation.id))
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
