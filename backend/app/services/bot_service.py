from __future__ import annotations

from datetime import datetime
import unicodedata

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import BotRule, Conversation, Message, Tenant
from app.services.whatsapp_service import WhatsAppConfigError, enviar_mensagem


def normalize(text: str) -> str:
    normalized = (text or "").lower().strip()
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = " ".join(normalized.split())
    return normalized


def _matches(rule: BotRule, incoming_text: str) -> bool:
    trigger_normalized = normalize(rule.trigger)
    message_normalized = normalize(incoming_text)
    print(f"[BOT MATCH] trigger={trigger_normalized} message={message_normalized}")
    if not trigger_normalized or not message_normalized:
        return False

    if rule.match_type == "exact":
        return trigger_normalized == message_normalized

    if rule.match_type == "contains":
        return trigger_normalized in message_normalized

    return trigger_normalized in message_normalized


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


def handle_bot(db: Session, message: Message, conversation) -> bool:
    print(f"[MODE CHECK] current mode={conversation.mode}")
    if conversation.mode != "bot":
        print("[BOT] envio automático bloqueado: modo diferente de bot")
        return False

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

    selected_response = None
    for rule in rules:
        if _matches(rule, message.text):
            selected_response = rule.response
            break

    if not selected_response:
        return False

    if tenant:
        try:
            print(f"[MODE CHECK] current mode={conversation.mode}")
            enviar_mensagem(
                conversation.phone_number,
                selected_response,
                token=tenant.whatsapp_token,
                phone_number_id=tenant.phone_number_id,
            )
        except WhatsAppConfigError:
            pass

    _create_outbound_message(
        db=db,
        conversation_id=conversation.id,
        tenant_id=conversation.tenant_id,
        text=selected_response,
    )
    if not message.from_me:
        conversation.last_bot_triggered_message_id = message.id
    conversation.updated_at = datetime.utcnow()
    return True


def get_last_message(db: Session, conversation_id) -> Message | None:
    return (
        db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
        )
        .scalars()
        .first()
    )


def handle_bot_activation(db: Session, conversation: Conversation) -> bool:
    if conversation.mode != "bot":
        return False

    last_message = get_last_message(db, conversation.id)
    if not last_message:
        return False

    if last_message.from_me:
        return False

    if conversation.last_bot_triggered_message_id == last_message.id:
        return False

    return handle_bot(db=db, message=last_message, conversation=conversation)
