from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.models.conversation import Conversation
from app.models.lead import Lead, LeadSource, LeadStage, LeadStatus, LeadTemperature
from app.services.audit_service import write_audit_log
from app.services.pipeline_service import get_first_pipeline_stage
from app.utils.phone import normalize_phone


@dataclass(frozen=True)
class LeadSoftDeleteResult:
    lead: Lead
    contact: Contact | None
    conversation: Conversation | None
    already_deleted: bool


def _lookup_lead_by_tenant_phone(db: Session, *, tenant_id: UUID, phone: str) -> Lead | None:
    normalized_phone = normalize_phone(phone)
    if not normalized_phone:
        return None
    return db.execute(
        select(Lead).where(Lead.tenant_id == tenant_id, Lead.phone == normalized_phone)
    ).scalars().first()


def _lookup_lead_by_tenant_id(db: Session, *, tenant_id: UUID, lead_id: UUID) -> Lead | None:
    return db.execute(
        select(Lead).where(Lead.tenant_id == tenant_id, Lead.id == lead_id)
    ).scalars().first()


def soft_delete_lead(
    db: Session,
    *,
    lead: Lead,
    user_id: UUID | None = None,
    audit_event: str = "Lead removido",
) -> LeadSoftDeleteResult:
    """Soft-delete a single Lead while preserving its Contact and Conversation.

    Leads use a status-based soft delete. The Contact and Conversation links are
    read for confirmation, but neither related record is modified or removed.
    """

    contact = None
    if lead.contact_id:
        contact = db.execute(
            select(Contact).where(Contact.tenant_id == lead.tenant_id, Contact.id == lead.contact_id)
        ).scalars().first()

    conversation = None
    if lead.conversation_id:
        conversation = db.execute(
            select(Conversation).where(
                Conversation.tenant_id == lead.tenant_id,
                Conversation.id == lead.conversation_id,
            )
        ).scalars().first()

    already_deleted = lead.status == LeadStatus.DELETED.value
    if not already_deleted:
        lead.status = LeadStatus.DELETED.value
        lead.updated_at = datetime.utcnow()
        write_audit_log(
            db,
            action="LEAD_DELETED",
            tenant_id=lead.tenant_id,
            user_id=user_id or lead.owner_id,
            entity_type="lead",
            entity_id=lead.id,
            metadata={
                "phone": lead.phone,
                "contact_id": str(lead.contact_id) if lead.contact_id else None,
                "conversation_id": str(lead.conversation_id) if lead.conversation_id else None,
                "event": audit_event,
                "soft_delete": True,
                "preserved_contact": bool(contact),
                "preserved_conversation": bool(conversation),
            },
        )
        db.flush()

    return LeadSoftDeleteResult(
        lead=lead,
        contact=contact,
        conversation=conversation,
        already_deleted=already_deleted,
    )


def soft_delete_lead_by_id(
    db: Session,
    *,
    tenant_id: UUID,
    lead_id: UUID,
    user_id: UUID | None = None,
    audit_event: str = "Lead removido",
) -> LeadSoftDeleteResult | None:
    lead = _lookup_lead_by_tenant_id(db, tenant_id=tenant_id, lead_id=lead_id)
    if not lead:
        return None
    return soft_delete_lead(db, lead=lead, user_id=user_id, audit_event=audit_event)


def soft_delete_lead_by_phone(
    db: Session,
    *,
    tenant_id: UUID,
    phone: str,
    user_id: UUID | None = None,
    audit_event: str = "Lead de teste removido",
) -> LeadSoftDeleteResult | None:
    """Soft-delete exactly one tenant-scoped Lead matched by normalized phone."""

    lead = _lookup_lead_by_tenant_phone(db, tenant_id=tenant_id, phone=phone)
    if not lead:
        return None
    return soft_delete_lead(db, lead=lead, user_id=user_id, audit_event=audit_event)


def get_or_create_lead(
    db: Session,
    tenant_id: UUID,
    phone: str,
    name: str | None = None,
    last_message: str | None = None,
) -> Lead:
    phone = normalize_phone(phone)
    print("PHONE:", phone)

    first_stage = get_first_pipeline_stage(db, tenant_id)
    default_stage_id = first_stage.id if first_stage else None

    lead = db.execute(
        select(Lead).where(Lead.tenant_id == tenant_id, Lead.phone == phone)
    ).scalars().first()

    if lead:
        lead.status = LeadStatus.ACTIVE.value
        lead.last_contact_at = datetime.utcnow()
        lead.last_interaction = datetime.utcnow()
        lead.last_message = last_message
        if not lead.stage_id and default_stage_id:
            lead.stage_id = default_stage_id
            lead.entered_stage_at = datetime.utcnow()
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
        lead = db.execute(
            select(Lead).where(Lead.tenant_id == tenant_id, Lead.phone == phone)
        ).scalars().first()
        if not lead:
            raise
        lead.status = LeadStatus.ACTIVE.value

    return lead
