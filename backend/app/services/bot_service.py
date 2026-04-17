from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BotRule, Message, Tenant
from app.services.whatsapp_service import WhatsAppConfigError, enviar_mensagem

FALLBACK_RESPONSE = "Recebi sua mensagem! Em instantes um atendente vai continuar por aqui."


def _matches(rule: BotRule, incoming_text: str) -> bool:
    trigger = (rule.trigger or "").strip().lower()
    text = (incoming_text or "").strip().lower()
    if not trigger or not text:
        return False

    if rule.match_type == "exact":
        return text == trigger

    return trigger in text


def _create_outbound_message(db: Session, conversation_id, tenant_id, text: str) -> Message:
    reply_message = Message(
        conversation_id=conversation_id,
        tenant_id=tenant_id,
        text=text,
        from_me=True,
        created_at=datetime.utcnow(),
    )
    db.add(reply_message)
    return reply_message


def handle_bot(db: Session, message: Message, conversation) -> Message:
    tenant = db.execute(select(Tenant).where(Tenant.id == conversation.tenant_id)).scalars().first()

    rules = (
        db.execute(
            select(BotRule)
            .where(BotRule.tenant_id == conversation.tenant_id)
            .order_by(BotRule.created_at.asc(), BotRule.id.asc())
        )
        .scalars()
        .all()
    )

    selected_response = FALLBACK_RESPONSE
    for rule in rules:
        if _matches(rule, message.text):
            selected_response = rule.response
            break

    if tenant:
        try:
            enviar_mensagem(
                conversation.phone_number,
                selected_response,
                token=tenant.whatsapp_token,
                phone_number_id=tenant.phone_number_id,
            )
        except WhatsAppConfigError:
            pass

    outbound = _create_outbound_message(
        db=db,
        conversation_id=conversation.id,
        tenant_id=conversation.tenant_id,
        text=selected_response,
    )
    conversation.updated_at = datetime.utcnow()
    return outbound
