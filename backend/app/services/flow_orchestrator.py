from __future__ import annotations

from sqlalchemy.orm import Session

from app.models import Conversation, Message
from app.services.flow_handlers import (
    fallback_inteligente,
    handle_positive,
    responder_funcionamento,
    responder_preco,
)

SHORT_POSITIVE_RESPONSES = {"sim", "quero", "ok", "claro", "pode", "isso"}


def _normalize_text(text: str | None) -> str:
    return (text or "").lower().strip()


def _retomar_fluxo(conversation: Conversation) -> str:
    if conversation.last_bot_question == "tipo_atendimento":
        return "Agora me diz: você prefere atendimento manual ou automático?"
    if conversation.last_bot_question == "interesse_planos":
        return "Agora me diz: quer ver os planos agora?"
    if conversation.last_bot_question == "plano":
        return "Agora me diz: qual plano você quer conhecer melhor?"
    return "Agora me diz: você quer seguir para vendas?"


def handle_flow(db: Session, message: Message, conversation: Conversation) -> str:
    del db
    conversation.current_objective = conversation.current_objective or "venda"
    normalized_message = _normalize_text(message.text)
    state = conversation.conversation_state or ""
    last_question = conversation.last_bot_question or ""

    if normalized_message in SHORT_POSITIVE_RESPONSES:
        response = handle_positive(conversation)
        if response:
            return response

    if "preço" in normalized_message or "preco" in normalized_message or "valor" in normalized_message:
        response = responder_preco(conversation)
        return f"{response}\n\n{_retomar_fluxo(conversation)}"

    if "como funciona" in normalized_message:
        response = responder_funcionamento(conversation)
        return f"{response}\n\n{_retomar_fluxo(conversation)}"

    if "o que faz" in normalized_message:
        conversation.last_bot_question = "interesse_planos"
        return (
            "A solução organiza seu atendimento, responde clientes e acelera suas vendas no WhatsApp.\n\n"
            "Agora me diz: você quer ver os planos?"
        )

    if "vendas" in normalized_message:
        conversation.conversation_state = "tipo_atendimento"
        conversation.last_bot_question = "tipo_atendimento"
        return "Perfeito 🔥 Você prefere atendimento manual ou automático?"

    if state == "tipo_atendimento":
        if "manual" in normalized_message:
            conversation.conversation_state = "apresentando_planos"
            conversation.last_bot_question = "interesse_planos"
            return "Ótimo 👌 atendimento manual é uma boa base. Quer ver os planos agora?"
        if "automatico" in normalized_message or "automático" in normalized_message:
            conversation.conversation_state = "apresentando_planos"
            conversation.last_bot_question = "interesse_planos"
            return "Boa escolha 🔥 atendimento automático acelera muito. Quer ver os planos agora?"

    if last_question == "plano":
        conversation.last_bot_question = "detalhe_plano"
        return "Top 🔥 Vou te explicar melhor esse plano agora. Agora me diz: quer que eu te mostre como começar?"

    return fallback_inteligente(conversation)
