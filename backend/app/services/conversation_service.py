from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from backend.app.models.conversation import Conversation
from backend.app.utils.phone import normalize_phone


def save_conversation(db: Session, phone: str, message: str, response: str, tenant_id):
    phone = normalize_phone(phone)
    print("PHONE_NORMALIZED:", phone)
    conv = (
        db.query(Conversation)
        .filter(Conversation.phone_number == phone, Conversation.tenant_id == tenant_id)
        .first()
    )

    if not conv:
        conv = Conversation(
            tenant_id=tenant_id,
            phone_number=phone,
            message=message,
            response=response,
        )
        db.add(conv)
    else:
        conv.message = message
        conv.response = response

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

        fallback_conv = (
            db.query(Conversation)
            .filter(Conversation.phone_number == phone, Conversation.tenant_id == tenant_id)
            .first()
        )
        if not fallback_conv:
            fallback_conv = Conversation(
                tenant_id=tenant_id,
                phone_number=phone,
                message=message,
            )
            db.add(fallback_conv)
        else:
            fallback_conv.message = message
        db.commit()
