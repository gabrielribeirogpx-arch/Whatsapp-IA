from __future__ import annotations

import unicodedata

from sqlalchemy.orm import Session

from app.models import Conversation, Message


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return without_accents.lower().strip()


def handle_flow(db: Session, conversation: Conversation, message: Message) -> str | None:
    step = conversation.current_step
    msg = _normalize_text(message.text)

    # INICIO
    if not step:
        conversation.current_step = "escolha_area"
        db.commit()
        return "Olá! 👋 Pra te ajudar melhor:\n\n1️⃣ Vendas\n2️⃣ Suporte\n3️⃣ Atendimento"

    # ESCOLHA AREA
    if step == "escolha_area":
        if "venda" in msg:
            conversation.current_step = "vendas"
            db.commit()
            return (
                "Perfeito 🔥 Você quer vender mais.\n\n"
                "Hoje você atende manualmente ou já usa automação?"
            )

    # VENDAS
    if step == "vendas":
        if "manual" in msg:
            conversation.current_step = "tipo_atendimento"
            db.commit()
            return (
                "Top 👍 Então você já pode automatizar.\n\n"
                "Quer algo mais automático ou com controle manual?"
            )

    # TIPO ATENDIMENTO
    if step == "tipo_atendimento":
        if "automatico" in msg:
            conversation.current_step = "planos"
            db.commit()
            return (
                "Perfeito 🚀 Vou te mostrar os planos:\n\n"
                "🔥 Básico — R$29,90\n"
                "🔥 Essencial — R$69,90\n"
                "🔥 PRO — R$129,90\n\n"
                "Qual te interessa?"
            )

    # PLANOS
    if step == "planos":
        if "basico" in msg:
            conversation.current_step = "fechamento"
            db.commit()
            return "Ótima escolha 👍\n\nQuer que eu já libere acesso pra você começar hoje?"

    # FECHAMENTO
    if step == "fechamento":
        if "sim" in msg:
            conversation.current_step = "finalizado"
            db.commit()
            return "🚀 Perfeito! Vou liberar seu acesso agora.\n\nSe precisar de ajuda é só chamar!"

    return None
