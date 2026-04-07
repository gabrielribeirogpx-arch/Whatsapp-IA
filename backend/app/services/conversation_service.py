from sqlalchemy.orm import Session

from backend.app.models.conversation import Conversation


def save_conversation(db: Session, phone: str, message: str, response: str):
    conv = Conversation(
        phone=phone,
        phone_number=phone,
        message=message,
        response=response,
    )
    db.add(conv)
    db.commit()
