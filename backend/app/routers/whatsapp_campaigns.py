from datetime import datetime
import re

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Contact, Tenant, WhatsAppCampaign, WhatsAppCampaignRecipient
from app.models.tenant_whatsapp_provider import TenantWhatsAppProvider
from app.models.whatsapp_message_template import WhatsAppMessageTemplate
from app.services.queue import get_queue
from app.services.tenant_service import get_current_tenant

router = APIRouter(prefix="/api/whatsapp/campaigns", tags=["whatsapp-campaigns"])


def _extract_template_variables(template: WhatsAppMessageTemplate) -> list[str]:
    text = "\n".join(
        [
            str(getattr(template, "body_text", "") or ""),
            str(getattr(template, "body_preview", "") or ""),
        ]
    )
    return sorted(set(re.findall(r"\{\{\s*(\d+)\s*\}\}", text)), key=lambda item: int(item))


def _serialize_campaign(c: WhatsAppCampaign) -> dict:
    return {
        "id": str(c.id), "name": c.name, "status": c.status, "provider_id": str(c.provider_id), "template_id": str(c.template_id),
        "total_recipients": c.total_recipients, "total_sent": c.total_sent, "total_delivered": c.total_delivered, "total_read": c.total_read, "total_failed": c.total_failed,
        "created_at": c.created_at.isoformat() if c.created_at else None,
    }


@router.get("")
def list_campaigns(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    rows = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.tenant_id == tenant.id).order_by(WhatsAppCampaign.created_at.desc())).scalars().all()
    return [_serialize_campaign(c) for c in rows]


@router.post("")
def create_campaign(payload: dict, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    campaign = WhatsAppCampaign(
        tenant_id=tenant.id,
        provider_id=payload.get("provider_id"),
        template_id=payload.get("template_id"),
        name=payload.get("name") or "Campanha",
        status="draft",
        created_by="console",
    )
    db.add(campaign); db.commit(); db.refresh(campaign)
    return _serialize_campaign(campaign)


@router.get("/{campaign_id}")
def get_campaign(campaign_id: str, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    c = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id, WhatsAppCampaign.tenant_id == tenant.id)).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    return _serialize_campaign(c)


@router.post("/{campaign_id}/recipients/import")
def import_recipients(campaign_id: str, payload: dict, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    c = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id, WhatsAppCampaign.tenant_id == tenant.id)).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    recipients = payload.get("recipients") or []

    imported = 0
    for item in recipients:
        if not item.get("phone"):
            continue
        db.add(WhatsAppCampaignRecipient(campaign_id=c.id, phone=item.get("phone"), first_name=item.get("first_name"), variables_json=item.get("variables_json") or {}))
        imported += 1
    c.total_recipients = int(c.total_recipients or 0) + imported
    db.commit()
    return {"ok": True, "imported": imported}



@router.post("/{campaign_id}/recipients/import-from-contacts")
def import_recipients_from_contacts(campaign_id: str, payload: dict, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    c = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id, WhatsAppCampaign.tenant_id == tenant.id)).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    ids = payload.get("contact_ids") or []
    if not ids:
        return {"ok": True, "imported": 0}
    contacts = db.execute(select(Contact).where(Contact.tenant_id == tenant.id, Contact.id.in_(ids))).scalars().all()
    variable_mapping = payload.get("variable_mapping") or {}
    manual_values = payload.get("manual_variable_values") or {}
    variable_mapping_payload = payload.get("variable_mapping_payload") or {}

    def _resolve_contact_value(contact: Contact, mapping_key: str, template_var: str) -> str:
        custom = contact.custom_fields_json or {}
        first_name_from_name = (str(contact.name or "").strip().split(" ", 1)[0] if contact.name else "").strip()
        if mapping_key == "first_name":
            return str(contact.first_name or "").strip() or first_name_from_name or "cliente"
        if mapping_key in {"full_name", "name"}:
            return str(contact.name or "").strip() or "cliente"
        if mapping_key == "phone":
            return str(contact.phone or "").strip()
        if mapping_key == "email":
            return str(contact.email or "").strip()
        if mapping_key == "order_number":
            return str(custom.get("order_number") or custom.get("pedido") or "").strip()
        if mapping_key == "manual_value":
            return str(manual_values.get(template_var) or "").strip()
        return ""


    def _resolve_mapping_payload(contact: Contact, template_var: str) -> tuple[str, str | None]:
        mapping = variable_mapping_payload.get(str(template_var)) or {}
        mapping_type = str(mapping.get("type") or "").strip()
        field = str(mapping.get("field") or "").strip()
        if mapping_type == "fixed":
            return str(mapping.get("value") or "").strip(), None
        if mapping_type == "contact_field":
            if field == "first_name":
                first_name_from_name = (str(contact.name or "").strip().split(" ", 1)[0] if contact.name else "").strip()
                return str(contact.first_name or "").strip() or first_name_from_name or "cliente", None
            if field in {"full_name", "name"}:
                return str(contact.name or "").strip() or "cliente", None
            if field == "phone":
                return str(contact.phone or "").strip(), None
            if field == "email":
                return str(contact.email or "").strip(), None
            return "", None
        if mapping_type == "custom_field":
            custom = contact.custom_fields_json if isinstance(contact.custom_fields_json, dict) else {}
            value = str(custom.get(field) or "").strip()
            if not value:
                return "", f"Campo personalizado {field} não existe para este contato. Use valor fixo ou importe esse campo no contato."
            return value, None
        return _resolve_contact_value(contact, str(variable_mapping.get(str(template_var)) or ""), str(template_var)), None

    imported = 0
    for contact in contacts:
        exists = db.execute(select(WhatsAppCampaignRecipient).where(WhatsAppCampaignRecipient.campaign_id == c.id, WhatsAppCampaignRecipient.phone == contact.phone)).scalars().first()
        if exists:
            continue
        first_name_from_name = (str(contact.name or "").strip().split(" ", 1)[0] if contact.name else "").strip()
        variables = {
            "first_name": str(contact.first_name or "").strip() or first_name_from_name or "cliente",
            "name": str(contact.name or "").strip() or "cliente",
            "phone": str(contact.phone or "").strip(),
            "order_number": str((contact.custom_fields_json or {}).get("order_number") or "").strip(),
        }
        mapping_errors: dict[str, str] = {}
        for template_var, mapping_key in variable_mapping.items():
            resolved_value, resolved_error = _resolve_mapping_payload(contact, str(template_var)) if variable_mapping_payload else (_resolve_contact_value(contact, str(mapping_key), str(template_var)), None)
            variables[str(template_var)] = resolved_value
            if resolved_error:
                mapping_errors[str(template_var)] = resolved_error
        variables["_variable_mapping"] = variable_mapping_payload
        if mapping_errors:
            variables["_variable_mapping_errors"] = mapping_errors
        db.add(WhatsAppCampaignRecipient(campaign_id=c.id, phone=contact.phone, first_name=contact.first_name or contact.name, variables_json=variables))
        imported += 1
    c.total_recipients = int(c.total_recipients or 0) + imported
    db.commit()
    return {"ok": True, "imported": imported}

@router.post("/{campaign_id}/start")
def start_campaign(campaign_id: str, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    c = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id, WhatsAppCampaign.tenant_id == tenant.id)).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if c.status == "running":
        raise HTTPException(status_code=400, detail="Campaign is already running")
    provider = db.execute(
        select(TenantWhatsAppProvider).where(
            TenantWhatsAppProvider.id == c.provider_id,
            TenantWhatsAppProvider.tenant_id == tenant.id,
        )
    ).scalars().first()
    if not provider or provider.status != "connected":
        raise HTTPException(status_code=400, detail="Provider is not connected/active")
    template = db.execute(
        select(WhatsAppMessageTemplate).where(
            WhatsAppMessageTemplate.id == c.template_id,
            WhatsAppMessageTemplate.tenant_id == tenant.id,
        )
    ).scalars().first()
    if not template or str(template.status or "").lower() != "approved":
        raise HTTPException(status_code=400, detail="Template is not approved")
    recipients = db.execute(select(WhatsAppCampaignRecipient).where(WhatsAppCampaignRecipient.campaign_id == c.id)).scalars().all()
    if not recipients:
        raise HTTPException(status_code=400, detail="Campaign has no recipients")
    required_vars = _extract_template_variables(template)
    if required_vars:
        for rec in recipients:
            vars_json = rec.variables_json if isinstance(rec.variables_json, dict) else {}
            missing = [var for var in required_vars if not str(vars_json.get(var) or "").strip()]
            if missing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Faltou preencher {', '.join(missing)}.",
                )
    c.status = "running"
    c.started_at = c.started_at or datetime.utcnow()
    db.commit()
    get_queue("normal").enqueue("app.workers.campaign_worker.process_campaign", str(c.id), str(tenant.id), job_timeout=600)
    db.refresh(c)
    return _serialize_campaign(c)


@router.post("/{campaign_id}/pause")
def pause_campaign(campaign_id: str, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    c = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id, WhatsAppCampaign.tenant_id == tenant.id)).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    c.status = "paused"; db.commit(); db.refresh(c)
    return _serialize_campaign(c)


@router.get("/{campaign_id}/recipients")
def list_recipients(campaign_id: str, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    c = db.execute(select(WhatsAppCampaign).where(WhatsAppCampaign.id == campaign_id, WhatsAppCampaign.tenant_id == tenant.id)).scalars().first()
    if not c:
        raise HTTPException(status_code=404, detail="Campaign not found")
    rows = db.execute(select(WhatsAppCampaignRecipient).where(WhatsAppCampaignRecipient.campaign_id == c.id).order_by(WhatsAppCampaignRecipient.created_at.desc())).scalars().all()
    return [{"id": str(r.id), "campaign_id": str(r.campaign_id), "phone": r.phone, "first_name": r.first_name, "status": r.status, "provider_message_id": r.provider_message_id, "error_message": r.error_message} for r in rows]
