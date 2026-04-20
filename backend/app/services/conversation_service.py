from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.conversation import Conversation
from app.utils.phone import normalize_phone


def save_conversation(db: Session, phone: str, message: str, tenant_id):
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
            conversation_state="inicio",
        )
        db.add(conv)

    try:
        db.commit()
    except SQLAlchemyError as exc:
        db.rollback()
        raise


def get_or_create_conversation(db: Session, tenant_id, phone: str, contact_id=None, message: str | None = None):
    normalized_phone = normalize_phone(phone)
    print("PHONE:", normalized_phone)

    conversation = db.execute(
        select(Conversation)
        .where(Conversation.tenant_id == tenant_id, Conversation.phone_number == normalized_phone)
        .order_by(desc(Conversation.updated_at), desc(Conversation.id))
    ).scalars().first()

    existed = conversation is not None
    if not conversation:
        conversation = Conversation(
            tenant_id=tenant_id,
            contact_id=contact_id,
            phone_number=normalized_phone,
            conversation_state="inicio",
        )
        db.add(conversation)
        try:
            with db.begin_nested():
                db.flush()
        except IntegrityError:
            conversation = db.execute(
                select(Conversation)
                .where(Conversation.tenant_id == tenant_id, Conversation.phone_number == normalized_phone)
                .order_by(desc(Conversation.updated_at), desc(Conversation.id))
            ).scalars().first()
            existed = True
            if conversation is None:
                raise

    if contact_id and conversation.contact_id is None:
        conversation.contact_id = contact_id

    print("CONVERSATION_ID:", conversation.id if conversation else None)
    print("EXISTENTE:", existed)
    return conversation, existed
