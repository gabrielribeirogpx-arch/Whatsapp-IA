from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.services.contact_event_service import register_contact_event
from app.services.realtime_service import sync_publish


@dataclass(frozen=True)
class ContactTagResult:
    contact: Any
    tags_json: list[str]
    added: bool


def add_tag_to_contact(
    db,
    *,
    tenant_id,
    contact,
    tag: str,
    description: str | None = None,
    metadata: dict | None = None,
    conversation=None,
    publish_realtime: bool = True,
) -> ContactTagResult | None:
    """Apply a tag to a tenant-owned contact using the shared CRM side effects."""
    normalized_tag = str(tag or "").strip()
    if not normalized_tag or contact is None:
        return None

    if str(getattr(contact, "tenant_id", "")) != str(tenant_id):
        return None

    tags = [str(existing).strip() for existing in list(getattr(contact, "tags_json", None) or []) if str(existing).strip()]
    added = normalized_tag not in tags
    if added:
        tags.append(normalized_tag)
        contact.tags_json = tags
        if hasattr(contact, "updated_at"):
            contact.updated_at = datetime.utcnow()
        register_contact_event(
            db,
            tenant_id=tenant_id,
            contact_id=contact.id,
            event_type="tag_added",
            title="Tag adicionada",
            description=description or normalized_tag,
            metadata=metadata or {"tag": normalized_tag},
            contact=contact,
        )
        if publish_realtime:
            publish_contact_tag_update(tenant_id=tenant_id, contact=contact, conversation=conversation)
    else:
        contact.tags_json = tags

    return ContactTagResult(contact=contact, tags_json=tags, added=added)


def publish_contact_tag_update(*, tenant_id, contact, conversation=None) -> None:
    """Publish a best-effort realtime update for inbox/sidebar/contact detail consumers."""
    payload = {
        "event": "contact_updated",
        "refresh": ["contacts", "conversations", "contact_details"],
        "contact_id": str(getattr(contact, "id", "")),
        "conversation_id": str(getattr(conversation, "id", "")) if conversation is not None else None,
        "phone": getattr(contact, "phone", None) or getattr(conversation, "phone_number", None),
        "tags_json": list(getattr(contact, "tags_json", None) or []),
        "contact": {
            "id": str(getattr(contact, "id", "")),
            "tenant_id": str(getattr(contact, "tenant_id", "")),
            "name": getattr(contact, "name", None),
            "phone": getattr(contact, "phone", None),
            "avatar_url": getattr(contact, "avatar_url", None),
            "tags_json": list(getattr(contact, "tags_json", None) or []),
            "score": getattr(contact, "score", 0) or 0,
            "lifecycle_stage": getattr(contact, "lifecycle_stage", None),
            "updated_at": getattr(contact, "updated_at", None).isoformat() if getattr(contact, "updated_at", None) else None,
        },
    }
    sync_publish(f"dashboard:{tenant_id}", payload)
    if conversation is not None:
        conversation_id = getattr(conversation, "id", None)
        if conversation_id:
            sync_publish(f"{tenant_id}:{conversation_id}", payload)
        phone_number = getattr(conversation, "phone_number", None)
        if phone_number:
            sync_publish(f"{tenant_id}:{phone_number}", payload)
