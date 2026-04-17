from sqlalchemy.orm import Session

from app.models import Conversation, Message
from app.services.bot_service import handle_bot


def handle_incoming_message(db: Session, message: Message, conversation: Conversation):
    mode = conversation.mode or "human"

    print(f"[ROUTER] mode={mode}")

    if mode == "human":
        return None
    elif mode == "bot":
        return handle_bot(db, message, conversation)

    return None
