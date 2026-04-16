from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import desc, select
from sqlalchemy.orm import Session, load_only

from app.database import get_db
from app.models import Conversation, Message, Product
from app.models.lead import LeadTemperature
from app.services.ai_provider import classificar_lead
from app.services.ai_service import generate_ai_response
from app.services.contact_sync_service import ensure_conversation_contact_link, upsert_contact_for_phone
from app.services.conversation_service import get_or_create_conversation
from app.services.lead_service import get_or_create_lead
from app.services.knowledge_service import build_rag_context, search_relevant_knowledge
from app.models import Tenant
from app.services.tenant_service import get_or_create_default_tenant
from app.services.whatsapp_service import enviar_mensagem
from app.utils.phone import normalize_phone

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


def _build_products_context(products: list[Product]) -> str:
    lines = ["Você é um vendedor. Aqui estão os produtos disponíveis:"]

    for index, product in enumerate(products, start=1):
        lines.extend(
            [
                f"Produto {index}:",
                f"- Nome: {product.name}",
                f"- Descrição: {product.description or '-'}",
                f"- Preço: {product.price or '-'}",
                f"- Benefícios: {product.benefits or '-'}",
                f"- Objeções comuns: {product.objections or '-'}",
                f"- Cliente ideal: {product.target_customer or '-'}",
            ]
        )

    lines.extend(
        [
            "",
            "REGRAS CRÍTICAS:",
            "- use os produtos acima para responder",
            "- sugira produto quando fizer sentido",
            "- não invente produto",
            "- responda como vendedor",
        ]
    )
    return "\n".join(lines)


def _join_prompt_with_products(products_context: str, prompt: str) -> str:
    return f"{products_context}\n\n{prompt.strip()}"


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


def _keyword_score(message: str) -> int:
    normalized = (message or "").strip().lower()
    if not normalized:
        return 0

    hot_keywords = ["comprar", "fechar", "agendar", "hoje", "urgente", "preço", "valor"]
    warm_keywords = ["interesse", "detalhes", "planos", "benefícios", "como funciona"]
    cold_keywords = ["depois", "talvez", "sem interesse", "não quero"]

    score = 0
    for keyword in hot_keywords:
        if keyword in normalized:
            score += 12
    for keyword in warm_keywords:
        if keyword in normalized:
            score += 6
    for keyword in cold_keywords:
        if keyword in normalized:
            score -= 10

    if "?" in normalized:
        score += 3

    return score


def _lead_to_updates(lead_level: str, current_score: int, incoming_message: str) -> tuple[str, int, str]:
    normalized = (lead_level or "").strip().lower()
    keyword_delta = _keyword_score(incoming_message)

    if normalized == "quente":
        temperature = LeadTemperature.HOT.value
        base_delta = 15
        stage = "quente"
    elif normalized == "frio":
        temperature = LeadTemperature.COLD.value
        base_delta = -5
        stage = "frio"
    else:
        temperature = LeadTemperature.WARM.value
        base_delta = 8
        stage = "morno"

    score = max(0, min(100, current_score + base_delta + keyword_delta))
    return stage, score, temperature


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

            ai_mode = tenant.ai_mode if tenant.ai_mode in {"atendente", "vendedor"} else "atendente"

            contact = upsert_contact_for_phone(
                db,
                tenant_id=tenant_id,
                phone=normalized_phone,
                name=contact_name,
            )

            conversation, existed = get_or_create_conversation(
                db=db,
                tenant_id=tenant_id,
                phone=normalized_phone,
                contact_id=contact.id,
                message=incoming_message,
            )

            if existed:
                print(f"Conversa encontrada: {conversation.id}")
            else:
                print(f"Nenhuma conversa encontrada, criando nova para {normalized_phone}")

            if contact_name and not conversation.name:
                conversation.name = contact_name
            ensure_conversation_contact_link(conversation, contact)
            conversation.message = incoming_message

            if conversation.name is None and _looks_like_name(incoming_message):
                conversation.name = incoming_message.strip()
            if conversation.name and (not contact.name or contact.name == "Cliente"):
                contact.name = conversation.name
            print("NOME CLIENTE:", conversation.name)

            contact.last_message_at = datetime.utcnow()

            print("LEAD_SYNC:", normalized_phone, tenant.id)
            lead = get_or_create_lead(
                db=db,
                tenant_id=tenant.id,
                phone=conversation.phone_number or normalized_phone,
                name=conversation.name,
                last_message=incoming_message,
            )

            print("SALVANDO_MSG:", normalized_phone, incoming_message)
            inbound_message = Message(
                tenant_id=conversation.tenant_id,
                conversation_id=conversation.id,
                text=incoming_message,
                from_me=False,
                created_at=datetime.utcnow(),
            )
            db.add(inbound_message)
            print("CONVERSA_ID:", conversation.id)
            print("MSG_SALVA:", inbound_message.text)

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

            lead_level = classificar_lead(incoming_message)
            contact.stage, contact.score, lead.temperature = _lead_to_updates(lead_level, contact.score, incoming_message)
            lead.score = contact.score
            lead.last_message = incoming_message
            lead.last_interaction = datetime.utcnow()
            lead.last_contact_at = datetime.utcnow()

            products = (
                db.execute(select(Product).where(Product.tenant_id == tenant_id).order_by(Product.created_at.asc(), Product.id.asc()))
                .scalars()
                .all()
            )

            if not products:
                auto_reply = "Nosso catálogo ainda não foi configurado"
            else:
                products_context = _build_products_context(products)

                if ai_mode == "vendedor":
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

                prompt = _join_prompt_with_products(products_context, prompt)
                knowledge_items = search_relevant_knowledge(
                    db=db,
                    tenant_id=tenant_id,
                    query_text=incoming_message,
                    top_k=5,
                )
                prompt = build_rag_context(prompt, knowledge_items)

                try:
                    auto_reply = await generate_ai_response(prompt)
                except Exception as e:
                    print(f"Erro IA: {e}")
                    auto_reply = "Desculpa, tive um erro aqui. Pode repetir?"

            print(f"IA respondeu: {auto_reply}")
            enviar_mensagem(
                normalized_phone,
                auto_reply,
                token=tenant.whatsapp_token,
                phone_number_id=tenant.phone_number_id,
            )

            print("SALVANDO_MSG:", normalized_phone, auto_reply)
            outbound_message = Message(
                tenant_id=conversation.tenant_id,
                conversation_id=conversation.id,
                text=auto_reply,
                from_me=True,
                created_at=datetime.utcnow(),
            )
            db.add(outbound_message)
            print("CONVERSA_ID:", conversation.id)
            print("MSG_SALVA:", outbound_message.text)
            conversation.message = auto_reply
            conversation.updated_at = datetime.utcnow()

            print("LEAD_SYNC:", normalized_phone, tenant.id)
            lead = get_or_create_lead(
                db=db,
                tenant_id=tenant.id,
                phone=conversation.phone_number or normalized_phone,
                name=conversation.name,
                last_message=auto_reply,
            )

            print(f"Evento processado (telefone={normalized_phone}, conteúdo={incoming_message})")
            print(f"Resposta automática enviada para {normalized_phone}")

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
