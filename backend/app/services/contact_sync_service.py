from datetime import datetime
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contact, Conversation


logger = logging.getLogger(__name__)
DEFAULT_CONTACT_NAME = "Cliente"


def upsert_contact_for_phone(
    db: Session,
    *,
    tenant_id,
    phone: str,
    name: str | None = None,
    source: str = "whatsapp",
    last_interaction_at: datetime | None = None,
    custom_fields_json: dict[str, Any] | None = None,
) -> Contact | None:
    safe_phone = str(phone or "").strip()
    if not safe_phone:
        return None

    cleaned_name = (name or "").strip() or None
    now = last_interaction_at or datetime.utcnow()
    safe_custom_fields = custom_fields_json if isinstance(custom_fields_json, dict) else {}

    logger.info("[CONTACT UPSERT START] tenant_id=%s phone=%s name=%s", tenant_id, safe_phone, cleaned_name or "n/a")

    contact = db.execute(
        select(Contact).where(Contact.tenant_id == tenant_id, Contact.phone == safe_phone)
    ).scalars().first()

    if not contact:
        first_name = cleaned_name.split(" ")[0] if cleaned_name else None
        last_name = " ".join(cleaned_name.split(" ")[1:]) if cleaned_name and len(cleaned_name.split(" ")) > 1 else None
        contact = Contact(
            tenant_id=tenant_id,
            phone=safe_phone,
            name=cleaned_name,
            first_name=first_name,
            last_name=last_name,
            source=source,
            tags=[],
            opt_in_status="unknown",
            last_message_at=now,
            last_interaction_at=now,
            custom_fields_json=safe_custom_fields,
        )
        if hasattr(contact, "stage") and getattr(contact, "stage", None) is None:
            setattr(contact, "stage", "novo")
        if hasattr(contact, "score") and getattr(contact, "score", None) is None:
            setattr(contact, "score", 0)
        db.add(contact)
        logger.info("[CONTACT UPSERT CREATED] contact_id=%s", contact.id or "pending")
    else:
        if cleaned_name:
            contact.name = cleaned_name
            parts = cleaned_name.split(" ")
            contact.first_name = parts[0] if parts else None
            contact.last_name = " ".join(parts[1:]) if len(parts) > 1 else None
        contact.source = source or contact.source
        contact.last_message_at = now
        contact.last_interaction_at = now
        if getattr(contact, "tags", None) is None:
            contact.tags = []
        if not getattr(contact, "opt_in_status", None):
            contact.opt_in_status = "unknown"
        if not isinstance(getattr(contact, "custom_fields_json", None), dict):
            contact.custom_fields_json = safe_custom_fields
        logger.info("[CONTACT UPSERT UPDATED] contact_id=%s", contact.id)

    db.flush()
    logger.info("[CONTACT UPSERT COMMIT OK] contact_id=%s", contact.id)
    return contact


def ensure_conversation_contact_link(conversation: Conversation, contact: Contact | None) -> None:
    if contact and not conversation.contact_id:
        conversation.contact_id = contact.id
