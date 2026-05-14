from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from app.models.contact import Contact


def apply_event_score(contact: Contact, event_type: str) -> None:
    if event_type == "message_received":
        contact.score = (contact.score or 0) + 5
    elif event_type == "campaign_received":
        contact.score = (contact.score or 0) + 10
    elif event_type == "flow_finished":
        contact.score = (contact.score or 0) + 20


def apply_inactivity_penalty(db: Session) -> int:
    cutoff = datetime.utcnow() - timedelta(days=7)
    updated = 0
    for contact in db.query(Contact).filter(Contact.last_interaction_at.isnot(None), Contact.last_interaction_at < cutoff).all():
        contact.score = max(0, (contact.score or 0) - 5)
        updated += 1
    return updated
