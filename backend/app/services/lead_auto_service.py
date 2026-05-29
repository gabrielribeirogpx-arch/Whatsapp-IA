from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Contact, Conversation, Lead, PipelineStage, TenantUser
from app.models.lead import LeadStage
from app.services.audit_service import write_audit_log
from app.services.pipeline_service import ensure_pipeline_stages
from app.utils.phone import normalize_phone

logger = logging.getLogger(__name__)

WHATSAPP_SOURCE = "whatsapp"
LEAD_CREATED_ACTION = "LEAD_CREATED"
DEFAULT_PIPELINE_STAGE_NAME = "Novo"


@dataclass(frozen=True)
class AutoLeadResult:
    lead: Lead
    created: bool
    pipeline_stage: PipelineStage | None


def _resolve_default_owner_id(db: Session, tenant_id: UUID) -> UUID | None:
    owner = db.execute(
        select(TenantUser)
        .where(
            TenantUser.tenant_id == tenant_id,
            TenantUser.status == "active",
            TenantUser.role == "owner",
        )
        .order_by(TenantUser.created_at.asc(), TenantUser.id.asc())
    ).scalars().first()
    if owner:
        return owner.id

    fallback = db.execute(
        select(TenantUser)
        .where(TenantUser.tenant_id == tenant_id, TenantUser.status == "active")
        .order_by(TenantUser.created_at.asc(), TenantUser.id.asc())
    ).scalars().first()
    return fallback.id if fallback else None


def _resolve_new_pipeline_stage(db: Session, tenant_id: UUID) -> PipelineStage | None:
    existing_stage_count = db.execute(
        select(PipelineStage.id).where(PipelineStage.tenant_id == tenant_id).limit(1)
    ).scalars().first()

    stages = ensure_pipeline_stages(db, tenant_id)
    stage = next(
        (item for item in stages if item.name.strip().lower() == DEFAULT_PIPELINE_STAGE_NAME.lower()),
        stages[0] if stages else None,
    )
    print(
        "[PIPELINE AUTO CREATED]"
        if existing_stage_count is None
        else "[PIPELINE AUTO CREATED] stage=Novo status=ready"
    )
    return stage


def ensure_whatsapp_lead_for_inbound(
    db: Session,
    *,
    tenant_id: UUID,
    phone: str,
    contact: Contact | None,
    conversation: Conversation | None,
    name: str | None = None,
    message_text: str | None = None,
    occurred_at: datetime | None = None,
) -> AutoLeadResult | None:
    """Ensure every inbound WhatsApp message is represented in CRM and pipeline.

    The dashboard reads lead/contact/conversation totals directly from the database,
    so creating/updating the lead in the same transaction makes dashboard numbers
    refresh on the next request without any manual operator action.
    """
    normalized_phone = normalize_phone(phone)
    if not normalized_phone:
        return None

    now = occurred_at or datetime.utcnow()
    lead = db.execute(
        select(Lead).where(Lead.tenant_id == tenant_id, Lead.phone == normalized_phone)
    ).scalars().first()

    if lead:
        if contact and not lead.contact_id:
            lead.contact_id = contact.id
        if conversation and not lead.conversation_id:
            lead.conversation_id = conversation.id
        if name and (not lead.name or lead.name == normalized_phone):
            lead.name = name
        if message_text is not None:
            lead.last_message = message_text
        lead.last_interaction = now
        lead.last_contact_at = now
        if not lead.source:
            lead.source = WHATSAPP_SOURCE
        if lead.score is None:
            lead.score = 0
        if not lead.stage_id:
            lead.stage_id = getattr(_resolve_new_pipeline_stage(db, tenant_id), "id", None)
        db.flush()
        return AutoLeadResult(lead=lead, created=False, pipeline_stage=None)

    pipeline_stage = _resolve_new_pipeline_stage(db, tenant_id)
    lead = Lead(
        tenant_id=tenant_id,
        phone=normalized_phone,
        name=(name or getattr(contact, "name", None) or normalized_phone),
        stage=LeadStage.LEAD.value,
        stage_id=pipeline_stage.id if pipeline_stage else None,
        temperature="cold",
        score=0,
        source=WHATSAPP_SOURCE,
        owner_id=_resolve_default_owner_id(db, tenant_id),
        contact_id=contact.id if contact else None,
        conversation_id=conversation.id if conversation else None,
        last_message=message_text,
        last_interaction=now,
        last_contact_at=now,
        created_at=now,
    )
    db.add(lead)
    db.flush()

    print("[LEAD AUTO CREATED]", f"tenant_id={tenant_id}", f"lead_id={lead.id}", f"phone={normalized_phone}")
    write_audit_log(
        db,
        action=LEAD_CREATED_ACTION,
        tenant_id=tenant_id,
        user_id=lead.owner_id,
        entity_type="lead",
        entity_id=lead.id,
        metadata={
            "source": WHATSAPP_SOURCE,
            "phone": normalized_phone,
            "contact_id": str(contact.id) if contact else None,
            "conversation_id": str(conversation.id) if conversation else None,
            "pipeline_stage_id": str(pipeline_stage.id) if pipeline_stage else None,
            "pipeline_stage": pipeline_stage.name if pipeline_stage else None,
            "automatic": True,
        },
    )
    print("[AUDIT LEAD CREATED]", f"tenant_id={tenant_id}", f"lead_id={lead.id}")
    logger.info(
        "event=lead_auto_created tenant_id=%s lead_id=%s contact_id=%s conversation_id=%s source=%s",
        tenant_id,
        lead.id,
        getattr(contact, "id", None),
        getattr(conversation, "id", None),
        WHATSAPP_SOURCE,
    )
    return AutoLeadResult(lead=lead, created=True, pipeline_stage=pipeline_stage)
