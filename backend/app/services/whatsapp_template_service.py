from datetime import datetime
from uuid import UUID
import asyncio

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.meta.meta_cloud_client import MetaApiError, MetaCloudClient
from app.models.tenant_whatsapp_provider import TenantWhatsAppProvider
from app.models.whatsapp_message_template import WhatsAppMessageTemplate
from app.utils.encryption import decrypt_secret


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
    provider = _resolve_provider(db, tenant_id, template.provider_id)
    if not provider:
        raise ValueError("Provider Meta não encontrado para submissão")
    token = decrypt_secret(provider.access_token_encrypted)
    if not token:
        raise ValueError("Token do provider inválido")

    try:
        resp = asyncio.run(_submit_meta_template(template, provider, token, str(tenant_id)))
        template.status = "pending"
        template.submitted_at = datetime.utcnow()
        template.external_template_id = resp.get("id")
        template.metadata_json = {**(template.metadata_json or {}), "meta_submit_response": resp}
        db.commit()
        db.refresh(template)
        return template
    except MetaApiError as exc:
        template.metadata_json = {**(template.metadata_json or {}), "last_error": str(exc)}
        db.commit()
        raise ValueError(str(exc)) from exc


def sync_templates_placeholder(db: Session, tenant_id: UUID):
    templates = list_templates(db, tenant_id)
    providers = db.execute(select(TenantWhatsAppProvider).where(TenantWhatsAppProvider.tenant_id == tenant_id, TenantWhatsAppProvider.provider_type == "meta_cloud")).scalars().all()
    synced = 0
    for provider in providers:
        token = decrypt_secret(provider.access_token_encrypted)
        if not token or not provider.waba_id:
            continue
        try:
            resp = asyncio.run(_list_meta_templates(provider, token, str(tenant_id)))
        except MetaApiError:
            continue
        remote = {item.get("name"): item for item in resp.get("data", [])}
        now = datetime.utcnow()
        for item in templates:
            mt = remote.get(item.name)
            if not mt:
                continue
            status = (mt.get("status") or "pending").lower()
            if status in {"approved", "rejected", "pending", "paused"}:
                item.status = status
            item.external_template_id = mt.get("id") or item.external_template_id
            item.rejection_reason = mt.get("rejected_reason") or item.rejection_reason
            item.last_synced_at = now
            synced += 1
    db.commit()
    return {"ok": True, "message": "Sincronização Meta executada.", "count": synced}


async def _submit_meta_template(template: WhatsAppMessageTemplate, provider: TenantWhatsAppProvider, token: str, tenant_id: str) -> dict:
    client = MetaCloudClient(token)
    payload = {
        "name": template.name,
        "language": template.language,
        "category": (template.category or "UTILITY").upper(),
        "components": _build_components(template),
    }
    return await client.post(f"/{provider.waba_id}/message_templates", payload=payload, context={"tenant_id": tenant_id, "provider_id": str(provider.id), "template_id": str(template.id)})


async def _list_meta_templates(provider: TenantWhatsAppProvider, token: str, tenant_id: str) -> dict:
    client = MetaCloudClient(token)
    return await client.get(f"/{provider.waba_id}/message_templates", context={"tenant_id": tenant_id, "provider_id": str(provider.id)})


def _build_components(template: WhatsAppMessageTemplate) -> list[dict]:
    components = [{"type": "BODY", "text": template.body_text}]
    if template.header_json and template.header_json.get("text"):
        components.append({"type": "HEADER", "format": "TEXT", "text": template.header_json.get("text")})
    if template.footer_text:
        components.append({"type": "FOOTER", "text": template.footer_text})
    if template.buttons_json:
        btns = []
        for btn in template.buttons_json:
            if isinstance(btn, dict) and btn.get("text"):
                btns.append({"type": "QUICK_REPLY", "text": btn.get("text")})
        if btns:
            components.append({"type": "BUTTONS", "buttons": btns})
    return components


def _resolve_provider(db: Session, tenant_id: UUID, provider_id: UUID | None):
    query = select(TenantWhatsAppProvider).where(TenantWhatsAppProvider.tenant_id == tenant_id, TenantWhatsAppProvider.provider_type == "meta_cloud")
    if provider_id:
        query = query.where(TenantWhatsAppProvider.id == provider_id)
    return db.execute(query).scalars().first()


def _get_template(db: Session, tenant_id: UUID, template_id: UUID):
    template = db.execute(select(WhatsAppMessageTemplate).where(WhatsAppMessageTemplate.id == template_id, WhatsAppMessageTemplate.tenant_id == tenant_id)).scalars().first()
    if not template:
        raise ValueError("Template não encontrado")
    return template
