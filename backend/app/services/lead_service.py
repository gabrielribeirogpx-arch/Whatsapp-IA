from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.lead import Lead, LeadSource, LeadStage, LeadStatus, LeadTemperature
from app.services.pipeline_service import get_first_pipeline_stage
from app.utils.phone import normalize_phone


def get_or_create_lead(
    db: Session,
    tenant_id: UUID,
    phone: str,
    name: str | None = None,
    last_message: str | None = None,
) -> Lead:
    phone = normalize_phone(phone)
    
    # AUDITORIA PROFUNDA
    all_leads = db.execute(
        select(Lead).where(
            Lead.tenant_id == tenant_id,
            Lead.phone == phone
        )
    ).scalars().all()
    
    print("[LEAD AUDIT]", [{"id": str(l.id), "status": l.status, "phone": l.phone} for l in all_leads])

    print(f"[LEAD LOOKUP] tenant_id={tenant_id} phone={phone} status_filter={LeadStatus.ACTIVE.value}")
    lead = db.execute(
        select(Lead).where(Lead.tenant_id == tenant_id, Lead.phone == phone, Lead.status == LeadStatus.ACTIVE.value)
    ).scalars().first()
    
    if lead:
        print(f"[LEAD FOUND] lead_id={lead.id} status={lead.status}")
        lead.last_contact_at = datetime.utcnow()
        lead.last_interaction = datetime.utcnow()
        lead.last_message = last_message
        return lead

    print("[LEAD CREATE] Tentando inserir novo lead")
    first_stage = get_first_pipeline_stage(db, tenant_id)
    default_stage_id = first_stage.id if first_stage else None

    lead = Lead(
        tenant_id=tenant_id,
        phone=phone,
        name=(name.strip() if name and name.strip() else None),
        stage=LeadStage.LEAD.value,
        stage_id=default_stage_id,
        temperature=LeadTemperature.COLD.value,
        score=0,
        last_message=last_message,
        source=LeadSource.WHATSAPP.value,
        status=LeadStatus.ACTIVE.value,
        last_interaction=datetime.utcnow(),
        last_contact_at=datetime.utcnow(),
        entered_stage_at=datetime.utcnow(),
    )
    db.add(lead)
    
    try:
        with db.begin_nested():
            db.flush()
    except IntegrityError:
        print("[LEAD INTEGRITY ERROR] Ocorreu colisão na constraint tenant/phone")
        lead = db.execute(
            select(Lead).where(Lead.tenant_id == tenant_id, Lead.phone == phone, Lead.status == LeadStatus.ACTIVE.value)
        ).scalars().first()
        if not lead:
            raise

    return lead
