from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Contact, Conversation, Lead, PipelineStage, TenantUser
from app.models.lead import LeadSource, LeadStage, LeadStatus
from app.services.audit_service import write_audit_log
from app.services.pipeline_service import get_first_pipeline_stage
from app.utils.phone import normalize_phone

logger = logging.getLogger(__name__)

WHATSAPP_SOURCE = LeadSource.WHATSAPP.value
LEAD_CREATED_ACTION = "LEAD_CREATED"


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
    stage = get_first_pipeline_stage(db, tenant_id)
    print("[PIPELINE INSERT]", f"tenant_id={tenant_id}", f"stage_id={getattr(stage, 'id', None)}")
    return stage


def _log_lead_event(tag: str, **fields) -> None:
    details = " ".join(f"{key}={value}" for key, value in fields.items())
    print(tag, details)
    logger.info("%s %s", tag, details)


def _lookup_lead_by_phone(db: Session, *, tenant_id: UUID, normalized_phone: str) -> Lead | None:
    _log_lead_event("[LEAD LOOKUP]", tenant_id=tenant_id, phone=normalized_phone)
    return db.execute(
        select(Lead).where(
            Lead.tenant_id == tenant_id,
            Lead.phone == normalized_phone,
        )
    ).scalars().first()


def _lookup_lead_by_contact(db: Session, *, tenant_id: UUID, contact: Contact | None) -> Lead | None:
    if not contact:
        return None
    return db.execute(
        select(Lead).where(
            Lead.tenant_id == tenant_id,
            Lead.contact_id == contact.id,
        )
    ).scalars().first()


def _apply_inbound_lead_updates(
    db: Session,
    *,
    lead: Lead,
    tenant_id: UUID,
    normalized_phone: str,
    contact: Contact | None,
    conversation: Conversation | None,
    name: str | None,
    message_text: str | None,
    now: datetime,
) -> None:
    if not lead.phone:
        lead.phone = normalized_phone
    if contact and not lead.contact_id:
        lead.contact_id = contact.id
    if conversation and not lead.conversation_id:
        lead.conversation_id = conversation.id
    if name and (not lead.name or lead.name == normalized_phone):
        lead.name = name
    if contact and getattr(contact, "email", None) and not getattr(lead, "email", None):
        lead.email = contact.email
    if message_text is not None:
        lead.last_message = message_text
    lead.last_interaction = now
    lead.last_contact_at = now
    lead.updated_at = now
    if not lead.source:
        lead.source = WHATSAPP_SOURCE
    if lead.score is None:
        lead.score = 0
    if not lead.stage_id:
        lead.stage_id = getattr(_resolve_new_pipeline_stage(db, tenant_id), "id", None)


def _flush_new_lead(db: Session, lead: Lead) -> None:
    if hasattr(db, "begin_nested"):
        with db.begin_nested():
            db.add(lead)
            db.flush()
        return
    db.add(lead)
    db.flush()


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
    conversation_created: bool = False,
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
    lead = _lookup_lead_by_phone(db, tenant_id=tenant_id, normalized_phone=normalized_phone)
    if not lead:
        lead = _lookup_lead_by_contact(db, tenant_id=tenant_id, contact=contact)

    if lead:
        _log_lead_event("[LEAD FOUND]", tenant_id=tenant_id, lead_id=lead.id, phone=normalized_phone)
        _apply_inbound_lead_updates(
            db,
            lead=lead,
            tenant_id=tenant_id,
            normalized_phone=normalized_phone,
            contact=contact,
            conversation=conversation,
            name=name,
            message_text=message_text,
            now=now,
        )
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
        email=getattr(contact, "email", None) if contact else None,
        source=WHATSAPP_SOURCE,
        status=LeadStatus.ACTIVE.value,
        owner_id=_resolve_default_owner_id(db, tenant_id),
        contact_id=contact.id if contact else None,
        conversation_id=conversation.id if conversation else None,
        last_message=message_text,
        last_interaction=now,
        last_contact_at=now,
        entered_stage_at=now,
        created_at=now,
        updated_at=now,
    )
    try:
        _flush_new_lead(db, lead)
    except IntegrityError:
        recovered = _lookup_lead_by_phone(db, tenant_id=tenant_id, normalized_phone=normalized_phone)
        if not recovered:
            raise
        _log_lead_event("[LEAD DUPLICATE RECOVERED]", tenant_id=tenant_id, lead_id=recovered.id, phone=normalized_phone)
        _apply_inbound_lead_updates(
            db,
            lead=recovered,
            tenant_id=tenant_id,
            normalized_phone=normalized_phone,
            contact=contact,
            conversation=conversation,
            name=name,
            message_text=message_text,
            now=now,
        )
        db.flush()
        _log_lead_event("[FLOW CONTINUING AFTER LEAD RECOVERY]", tenant_id=tenant_id, lead_id=recovered.id, phone=normalized_phone)
        return AutoLeadResult(lead=recovered, created=False, pipeline_stage=None)

    _log_lead_event("[LEAD CREATED]", tenant_id=tenant_id, lead_id=lead.id, phone=normalized_phone)
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
            "event": "Novo lead criado",
        },
    )
    print("[AUDIT LEAD CREATED]", f"tenant_id={tenant_id}", f"lead_id={lead.id}")
    if conversation_created and conversation:
        write_audit_log(
            db,
            action="CONVERSATION_STARTED",
            tenant_id=tenant_id,
            user_id=lead.owner_id,
            entity_type="conversation",
            entity_id=conversation.id,
            metadata={"phone": normalized_phone, "lead_id": str(lead.id), "event": "Nova conversa iniciada"},
        )
    logger.info(
        "event=lead_auto_created tenant_id=%s lead_id=%s contact_id=%s conversation_id=%s source=%s",
        tenant_id,
        lead.id,
        getattr(contact, "id", None),
        getattr(conversation, "id", None),
        WHATSAPP_SOURCE,
    )
    return AutoLeadResult(lead=lead, created=True, pipeline_stage=pipeline_stage)
