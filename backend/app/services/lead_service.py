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
    print(f"[LEAD SERVICE FILE] {__file__}")
    phone = normalize_phone(phone)
    
    # 1. Busca abrangente (ignora status para evitar colisão)
    lead = db.execute(
        select(Lead).where(
            Lead.tenant_id == tenant_id,
            Lead.phone == phone
        )
    ).scalars().first()
    
    # 2. Configuração de Pipeline
    first_stage = get_first_pipeline_stage(db, tenant_id)
    first_stage_id = first_stage.id if first_stage else None

    # 3. Lógica de Reativação ou Atualização
    if lead:
        old_status = lead.status
        if old_status != LeadStatus.ACTIVE.value:
            print(f"[LEAD REACTIVATED] lead_id={lead.id} old_status={old_status}")
            lead.status = LeadStatus.ACTIVE.value
            lead.stage_id = first_stage_id
            lead.entered_stage_at = datetime.utcnow()
        
        lead.last_contact_at = datetime.utcnow()
        lead.last_interaction = datetime.utcnow()
        lead.last_message = last_message
        if name and name.strip():
            lead.name = name.strip()
        
        return lead
    
    # 4. Criação de novo lead
    print("[LEAD CREATE] Criando novo lead")
    lead = Lead(
        tenant_id=tenant_id,
        phone=phone,
        name=(name.strip() if name and name.strip() else None),
        stage=LeadStage.LEAD.value,
        stage_id=first_stage_id,
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
        raise

    return lead
