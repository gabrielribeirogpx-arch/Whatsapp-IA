from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models.lead import Lead
from backend.app.utils.phone import normalize_phone


def get_or_create_lead(
    db: Session,
    tenant_id: UUID,
    phone: str,
    name: str | None = None,
    last_message: str | None = None,
) -> Lead:
    phone = normalize_phone(phone)
    print("PHONE_NORMALIZED:", phone)

    lead = db.execute(
        select(Lead).where(Lead.tenant_id == tenant_id, Lead.phone == phone)
    ).scalars().first()

    if lead:
        lead.last_contact_at = datetime.utcnow()
        lead.last_message = last_message
        if name and name.strip():
            lead.name = name.strip()
        return lead

    lead = Lead(
        tenant_id=tenant_id,
        phone=phone,
        name=(name.strip() if name and name.strip() else None),
        stage="lead",
        score=0,
        last_message=last_message,
        last_contact_at=datetime.utcnow(),
    )
    db.add(lead)
    db.flush()
    return lead
