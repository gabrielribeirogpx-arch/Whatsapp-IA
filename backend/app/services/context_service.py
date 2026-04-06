from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Conversation, Message


def build_context(db: Session, tenant_id: int, phone: str, limit: int = 10) -> list[Message]:
    conversation = db.execute(
        select(Conversation).where(Conversation.tenant_id == tenant_id, Conversation.phone == phone)
    ).scalar_one_or_none()
    if not conversation:
        return []

    recent = (
        db.execute(
            select(Message)
            .where(Message.tenant_id == tenant_id, Message.conversation_id == conversation.id)
            .order_by(Message.timestamp.desc(), Message.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    return list(reversed(recent))
