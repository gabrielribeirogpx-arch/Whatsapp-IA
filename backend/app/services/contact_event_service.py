from __future__ import annotations

from datetime import datetime

from app.models.contact_event import ContactEvent
from app.services.contact_scoring_service import apply_event_score


def register_contact_event(db, *, tenant_id, contact_id, event_type: str, title: str, description: str | None = None, metadata: dict | None = None, contact=None):
    event = ContactEvent(tenant_id=tenant_id, contact_id=contact_id, type=event_type, title=title, description=description, metadata_json=metadata or {}, created_at=datetime.utcnow())
    db.add(event)
    if contact is not None:
        contact.last_interaction_at = datetime.utcnow()
        apply_event_score(contact, event_type)
    return event
