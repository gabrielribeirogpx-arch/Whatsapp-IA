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
from app.services.realtime_service import sync_publish
from app.utils.phone import normalize_phone

logger = logging.getLogger(__name__)

WHATSAPP_SOURCE = LeadSource.WHATSAPP.value
LEAD_CREATED_ACTION = "LEAD_CREATED"
FLOW_LEAD_CREATED_ACTION = "FLOW_LEAD_CREATED"
FLOW_LEAD_UPDATED_ACTION = "FLOW_LEAD_UPDATED"


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


def _lookup_contact_by_id(db: Session, *, tenant_id: UUID, contact_id) -> Contact | None:
    if not contact_id:
        return None
    return db.execute(
        select(Contact).where(
            Contact.tenant_id == tenant_id,
            Contact.id == contact_id,
        )
    ).scalars().first()


def _lookup_contact_by_phone(db: Session, *, tenant_id: UUID, normalized_phone: str) -> Contact | None:
    return db.execute(
        select(Contact).where(
            Contact.tenant_id == tenant_id,
            Contact.phone == normalized_phone,
        )
    ).scalars().first()


def _lookup_conversation_by_id(db: Session, *, tenant_id: UUID, conversation_id) -> Conversation | None:
    if not conversation_id:
        return None
    return db.execute(
        select(Conversation).where(
            Conversation.tenant_id == tenant_id,
            Conversation.id == conversation_id,
        )
    ).scalars().first()


def _lookup_conversation_by_phone(db: Session, *, tenant_id: UUID, normalized_phone: str) -> Conversation | None:
    return db.execute(
        select(Conversation).where(
            Conversation.tenant_id == tenant_id,
            Conversation.phone_number == normalized_phone,
        )
    ).scalars().first()


def _metadata_contact_name(metadata: dict | None) -> str | None:
    if not isinstance(metadata, dict):
        return None
    for key in ("contact_name", "name"):
        value = str(metadata.get(key) or "").strip()
        if value:
            return value
    contact_metadata = metadata.get("contact")
    if isinstance(contact_metadata, dict):
        value = str(contact_metadata.get("name") or "").strip()
        if value:
            return value
    return None


def _publish_flow_lead_realtime(
    *,
    tenant_id: UUID,
    lead: Lead,
    created: bool,
    contact: Contact | None,
    conversation: Conversation | None,
) -> None:
    payload = {
        "event": "lead_created" if created else "lead_updated",
        "type": "LEAD_CREATED" if created else "LEAD_UPDATED",
        "refresh": [
            "analytics",
            "activity",
            "conversations",
            "contacts",
            "leads",
            "pipeline",
            "contact_details",
        ],
        "lead_id": str(getattr(lead, "id", "")),
        "contact_id": str(getattr(contact, "id", "") or getattr(lead, "contact_id", "") or "")
        or None,
        "conversation_id": str(
            getattr(conversation, "id", "") or getattr(lead, "conversation_id", "") or ""
        )
        or None,
        "phone": getattr(lead, "phone", None),
        "lead": {
            "id": str(getattr(lead, "id", "")),
            "tenant_id": str(getattr(lead, "tenant_id", "")),
            "phone": getattr(lead, "phone", None),
            "name": getattr(lead, "name", None),
            "contact_id": str(getattr(lead, "contact_id", ""))
            if getattr(lead, "contact_id", None)
            else None,
            "conversation_id": str(getattr(lead, "conversation_id", ""))
            if getattr(lead, "conversation_id", None)
            else None,
            "stage_id": str(getattr(lead, "stage_id", "")) if getattr(lead, "stage_id", None) else None,
            "status": getattr(lead, "status", None),
            "source": getattr(lead, "source", None),
            "last_message": getattr(lead, "last_message", None),
            "last_interaction": getattr(lead, "last_interaction", None).isoformat()
            if getattr(lead, "last_interaction", None)
            else None,
            "last_contact_at": getattr(lead, "last_contact_at", None).isoformat()
            if getattr(lead, "last_contact_at", None)
            else None,
            "updated_at": getattr(lead, "updated_at", None).isoformat()
            if getattr(lead, "updated_at", None)
            else None,
        },
    }
    sync_publish(f"dashboard:{tenant_id}", payload)
    if conversation is not None:
        conversation_id = getattr(conversation, "id", None)
        if conversation_id:
            sync_publish(f"{tenant_id}:{conversation_id}", payload)
        phone_number = getattr(conversation, "phone_number", None) or getattr(lead, "phone", None)
        if phone_number:
            sync_publish(f"{tenant_id}:{phone_number}", payload)


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
            "contact_name": name or getattr(contact, "name", None),
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
            metadata={"phone": normalized_phone, "contact_name": name or getattr(contact, "name", None), "lead_id": str(lead.id), "event": "Nova conversa iniciada"},
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


def create_or_update_lead_from_flow_action(
    db: Session,
    *,
    tenant_id: UUID,
    phone: str,
    contact_id=None,
    conversation_id=None,
    lead_name: str | None = None,
    last_message: str | None = None,
    metadata: dict | None = None,
) -> AutoLeadResult | None:
    """Create/update a WhatsApp CRM lead from the Runtime V2 Create Lead action.

    This Flow Builder adapter reuses the official inbound lead path so tenant
    isolation, pipeline defaults, duplicate recovery and base CRM fields stay
    consistent with WhatsApp inbound processing.
    """
    normalized_phone = normalize_phone(phone)
    if not normalized_phone:
        logger.warning("[FLOW CREATE LEAD SKIPPED] tenant_id=%s reason=missing_phone", tenant_id)
        return None

    contact = _lookup_contact_by_id(db, tenant_id=tenant_id, contact_id=contact_id)
    if contact is None:
        contact = _lookup_contact_by_phone(db, tenant_id=tenant_id, normalized_phone=normalized_phone)

    conversation = _lookup_conversation_by_id(db, tenant_id=tenant_id, conversation_id=conversation_id)
    if conversation is None:
        conversation = _lookup_conversation_by_phone(db, tenant_id=tenant_id, normalized_phone=normalized_phone)

    resolved_name = (
        str(lead_name or "").strip()
        or _metadata_contact_name(metadata)
        or str(getattr(contact, "name", None) or "").strip()
        or None
    )
    result = ensure_whatsapp_lead_for_inbound(
        db,
        tenant_id=tenant_id,
        phone=normalized_phone,
        contact=contact,
        conversation=conversation,
        name=resolved_name,
        message_text=last_message,
    )
    if result is None:
        return None

    if lead_name and str(lead_name).strip():
        result.lead.name = str(lead_name).strip()
    if contact is not None:
        result.lead.contact_id = getattr(contact, "id", None)
    if conversation is not None:
        result.lead.conversation_id = getattr(conversation, "id", None)
    result.lead.status = LeadStatus.ACTIVE.value

    action = FLOW_LEAD_CREATED_ACTION if result.created else FLOW_LEAD_UPDATED_ACTION
    event = (
        "Lead criado automaticamente pelo Flow Builder."
        if result.created
        else "Lead atualizado automaticamente pelo Flow Builder."
    )
    write_audit_log(
        db,
        action=action,
        tenant_id=tenant_id,
        user_id=getattr(result.lead, "owner_id", None),
        entity_type="lead",
        entity_id=getattr(result.lead, "id", None),
        metadata={
            "source": "flow_builder",
            "phone": normalized_phone,
            "contact_name": resolved_name,
            "contact_id": str(getattr(contact, "id", "")) if contact else None,
            "conversation_id": str(getattr(conversation, "id", "")) if conversation else None,
            "lead_id": str(getattr(result.lead, "id", "")),
            "created": result.created,
            "automatic": True,
            "event": event,
        },
    )

    try:
        _publish_flow_lead_realtime(
            tenant_id=tenant_id,
            lead=result.lead,
            created=result.created,
            contact=contact,
            conversation=conversation,
        )
    except Exception:
        logger.exception(
            "[FLOW CREATE LEAD REALTIME FAILED] tenant_id=%s lead_id=%s",
            tenant_id,
            getattr(result.lead, "id", None),
        )

    return result
