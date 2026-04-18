from __future__ import annotations

from app.models import Conversation
from app.services.product_service import build_products_response, get_active_products
from sqlalchemy.orm import Session


def handle_positive(conversation: Conversation) -> str:
    if conversation.last_bot_question == "interesse_planos":
        conversation.conversation_state = "plano"
        conversation.last_bot_question = "plano"
        return "Temos alguns planos disponíveis. Qual você quer ver agora?"

    if conversation.last_bot_question == "plano":
        conversation.last_bot_question = "detalhe_plano"
        return "Top 🔥 Vou te explicar melhor esse plano agora. Agora me diz: você quer fechar hoje?"

    conversation.last_bot_question = "tipo_atendimento"
    return "Perfeito 🔥 Você prefere atendimento manual ou automático?"


def responder_preco(db: Session, conversation: Conversation) -> str:
    conversation.last_bot_question = "escolha_inicio"
    products = get_active_products(db=db, tenant_id=conversation.tenant_id)
    return build_products_response(products)


def responder_funcionamento(conversation: Conversation) -> str:
    conversation.last_bot_question = "interesse_planos"
    return (
        "Funciona assim 👇\n\n"
        "1 Cliente chama no WhatsApp\n"
        "2 Bot responde automaticamente\n"
        "3 Qualifica o cliente\n"
        "4 Você entra só quando precisa\n\n"
        "Quer ver os planos agora?"
    )


def fallback_inteligente(conversation: Conversation) -> str:
    conversation.last_bot_question = "fallback"
    return "Entendi 👍 Me explica melhor o que você quer fazer?"
