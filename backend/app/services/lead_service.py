from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.lead import Lead, LeadStage, LeadTemperature
from app.services.pipeline_service import ensure_pipeline_stages
from app.utils.phone import normalize_phone


def get_or_create_lead(
    db: Session,
    tenant_id: UUID,
    phone: str,
    name: str | None = None,
    last_message: str | None = None,
) -> Lead:
    phone = normalize_phone(phone)
    print("PHONE:", phone)

    stages = ensure_pipeline_stages(db, tenant_id)
    default_stage_id = stages[0].id if stages else None

    lead = db.execute(
        select(Lead).where(Lead.tenant_id == tenant_id, Lead.phone == phone)
    ).scalars().first()

    if lead:
        lead.last_contact_at = datetime.utcnow()
        lead.last_interaction = datetime.utcnow()
        lead.last_message = last_message
        if not lead.stage_id and default_stage_id:
            lead.stage_id = default_stage_id
        if name and name.strip():
            lead.name = name.strip()
        return lead

    lead = Lead(
        tenant_id=tenant_id,
        phone=phone,
        name=(name.strip() if name and name.strip() else None),
        stage=LeadStage.LEAD.value,
        stage_id=default_stage_id,
        temperature=LeadTemperature.COLD.value,
        score=0,
        last_message=last_message,
        last_interaction=datetime.utcnow(),
        last_contact_at=datetime.utcnow(),
    )
    db.add(lead)

    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        lead = db.execute(
            select(Lead).where(Lead.tenant_id == tenant_id, Lead.phone == phone)
        ).scalars().first()
        if not lead:
            raise

    return lead
