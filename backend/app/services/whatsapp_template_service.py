from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.whatsapp_message_template import WhatsAppMessageTemplate


def list_templates(db: Session, tenant_id: UUID):
    return db.execute(select(WhatsAppMessageTemplate).where(WhatsAppMessageTemplate.tenant_id == tenant_id)).scalars().all()


def create_template(db: Session, tenant_id: UUID, payload):
    template = WhatsAppMessageTemplate(tenant_id=tenant_id, **payload.model_dump(exclude_unset=True))
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def update_template(db: Session, tenant_id: UUID, template_id: UUID, payload):
    template = _get_template(db, tenant_id, template_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(template, key, value)
    db.commit()
    db.refresh(template)
    return template


def delete_template(db: Session, tenant_id: UUID, template_id: UUID):
    template = _get_template(db, tenant_id, template_id)
    db.delete(template)
    db.commit()


def submit_template_placeholder(db: Session, tenant_id: UUID, template_id: UUID):
    template = _get_template(db, tenant_id, template_id)
    if template.status == "draft":
        template.status = "submitted"
    template.status = "pending"
    template.submitted_at = datetime.utcnow()
    template.metadata_json = {**(template.metadata_json or {}), "integration": "provider integration pending"}
    db.commit()
    db.refresh(template)
    return template


def sync_templates_placeholder(db: Session, tenant_id: UUID):
    templates = list_templates(db, tenant_id)
    now = datetime.utcnow()
    for item in templates:
        item.last_synced_at = now
    db.commit()
    return {"ok": True, "message": "Sincronização placeholder executada com segurança.", "count": len(templates)}


def _get_template(db: Session, tenant_id: UUID, template_id: UUID):
    template = db.execute(select(WhatsAppMessageTemplate).where(WhatsAppMessageTemplate.id == template_id, WhatsAppMessageTemplate.tenant_id == tenant_id)).scalars().first()
    if not template:
        raise ValueError("Template não encontrado")
    return template
