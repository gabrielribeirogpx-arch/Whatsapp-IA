from datetime import datetime
import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contact, Conversation


DEFAULT_CONTACT_NAME = "Cliente"


def upsert_contact_for_phone(
    db: Session,
    *,
    tenant_id,
    phone: str,
    name: str | None = None,
    source: str = "whatsapp",
) -> Contact:
    contact = db.execute(
        select(Contact).where(Contact.tenant_id == tenant_id, Contact.phone == phone)
    ).scalars().first()

    cleaned_name = (name or "").strip() or None
    now = datetime.utcnow()

    if not contact:
        first_name = (cleaned_name.split(" ")[0] if cleaned_name else None)
        last_name = (" ".join(cleaned_name.split(" ")[1:]) if cleaned_name and len(cleaned_name.split(" ")) > 1 else None)
        contact = Contact(
            tenant_id=tenant_id,
            phone=phone,
            name=cleaned_name or DEFAULT_CONTACT_NAME,
            first_name=first_name,
            last_name=last_name,
            source=source,
            stage="novo",
            score=0,
            last_message_at=now,
            last_interaction_at=now,
            custom_fields_json={},
        )
        db.add(contact)
        db.flush()
        return contact

    if cleaned_name and cleaned_name != contact.name:
        contact.name = cleaned_name
        parts = cleaned_name.split(" ")
        contact.first_name = parts[0] if parts else contact.first_name
        contact.last_name = " ".join(parts[1:]) if len(parts) > 1 else contact.last_name

    if source and not contact.source:
        contact.source = source

    contact.last_message_at = now
    contact.last_interaction_at = now
    return contact


def ensure_conversation_contact_link(conversation: Conversation, contact: Contact) -> None:
    if not conversation.contact_id:
        conversation.contact_id = contact.id

