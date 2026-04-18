from __future__ import annotations

from app.models import Conversation


def handle_positive(conversation: Conversation) -> str:
    if conversation.last_bot_question == "interesse_planos":
        conversation.conversation_state = "plano"
        conversation.last_bot_question = "plano"
        return "Temos Básico, Essencial e PRO. Qual você quer ver agora?"

    if conversation.last_bot_question == "plano":
        conversation.last_bot_question = "detalhe_plano"
        return "Top 🔥 Vou te explicar melhor esse plano agora. Agora me diz: você quer fechar hoje?"

    conversation.last_bot_question = "tipo_atendimento"
    return "Perfeito 🔥 Você prefere atendimento manual ou automático?"


def responder_preco(conversation: Conversation) -> str:
    conversation.last_bot_question = "escolha_inicio"
    return (
        "Os valores variam por plano 👍\n\n"
        "Básico: R$29\n"
        "Essencial: R$69\n"
        "PRO: R$129\n\n"
        "Agora me diz: você quer começar mais simples ou já escalar?"
    )


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
