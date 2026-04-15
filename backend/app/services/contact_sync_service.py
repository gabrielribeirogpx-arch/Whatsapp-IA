from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import Contact, Conversation


DEFAULT_CONTACT_NAME = "Cliente"


def upsert_contact_for_phone(
    db: Session,
    *,
    tenant_id,
    phone: str,
    name: str | None = None,
) -> Contact:
    contact = db.execute(
        select(Contact).where(Contact.tenant_id == tenant_id, Contact.phone == phone)
    ).scalars().first()

    cleaned_name = (name or "").strip() or None
    now = datetime.utcnow()

    if not contact:
        contact = Contact(
            tenant_id=tenant_id,
            phone=phone,
            name=cleaned_name or DEFAULT_CONTACT_NAME,
            stage="novo",
            score=0,
            last_message_at=now,
        )
        db.add(contact)
        db.flush()
        return contact

    if cleaned_name and cleaned_name != contact.name:
        contact.name = cleaned_name

    contact.last_message_at = now
    return contact


def ensure_conversation_contact_link(conversation: Conversation, contact: Contact) -> None:
    if not conversation.contact_id:
        conversation.contact_id = contact.id

