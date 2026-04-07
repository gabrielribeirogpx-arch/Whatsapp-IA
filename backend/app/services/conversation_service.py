from sqlalchemy.orm import Session
from sqlalchemy.exc import SQLAlchemyError

from backend.app.models.conversation import Conversation


def save_conversation(db: Session, phone: str, message: str, response: str):
    conv = Conversation(
        phone_number=phone,
        message=message,
        response=response,
    )
    db.add(conv)

    try:
        _ = conv.response
    except Exception:
        pass

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        if "conversations.response" not in str(exc):
            raise

        fallback_conv = Conversation(
            phone_number=phone,
            message=message,
        )
        db.add(fallback_conv)
        db.commit()
