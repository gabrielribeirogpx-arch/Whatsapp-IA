from datetime import datetime
from uuid import UUID
import asyncio
import logging
import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.meta.meta_cloud_client import MetaApiError, MetaCloudClient
from app.models.tenant_whatsapp_provider import TenantWhatsAppProvider
from app.models.whatsapp_message_template import WhatsAppMessageTemplate
from app.utils.encryption import decrypt_secret

logger = logging.getLogger(__name__)


class TemplateSubmitError(Exception):
    def __init__(self, detail: str, status_code: int, meta_error: str | None = None, meta_code: str | int | None = None):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code
        self.meta_error = meta_error
        self.meta_code = str(meta_code) if meta_code is not None else None


def list_templates(db: Session, tenant_id: UUID):
    return db.execute(select(WhatsAppMessageTemplate).where(WhatsAppMessageTemplate.tenant_id == tenant_id)).scalars().all()


def create_template(db: Session, tenant_id: UUID, payload):
    data = payload.model_dump(exclude_unset=True)
    body_raw_meta = (data.pop("body_raw_meta", None) or data.get("body_text") or "").strip()
    body_preview = data.pop("body_preview", None)
    data["body_text"] = body_raw_meta
    metadata = dict(data.get("metadata_json") or {})
    if body_preview is not None:
        metadata["body_preview"] = body_preview
    data["metadata_json"] = metadata
    template = WhatsAppMessageTemplate(tenant_id=tenant_id, **data)
    db.add(template)
    db.commit()
    db.refresh(template)
    return template


def update_template(db: Session, tenant_id: UUID, template_id: UUID, payload):
    template = _get_template(db, tenant_id, template_id)
    data = payload.model_dump(exclude_unset=True)
    if "body_raw_meta" in data:
        data["body_text"] = (data.pop("body_raw_meta") or "").strip()
    body_preview = data.pop("body_preview", None) if "body_preview" in data else None
    for key, value in data.items():
        setattr(template, key, value)
    if "body_preview" in payload.model_fields_set:
        metadata = dict(template.metadata_json or {})
        metadata["body_preview"] = body_preview
        template.metadata_json = metadata
    db.commit()
    db.refresh(template)
    return template


def delete_template(db: Session, tenant_id: UUID, template_id: UUID):
    template = _get_template(db, tenant_id, template_id)
    db.delete(template)
    db.commit()


def submit_template_placeholder(db: Session, tenant_id: UUID, template_id: UUID):
    print(f"[SUBMIT DEBUG] step=find_template tenant_id={tenant_id} template_id={template_id}")
    template = _get_template(db, tenant_id, template_id, raise_not_found=True)
    print(f"[SUBMIT DEBUG] step=template_found provider_id={template.provider_id}")

    print(f"[SUBMIT DEBUG] step=find_provider provider_id={template.provider_id}")
    provider = _resolve_provider_for_submit(db, tenant_id, template)
    print(
        f"[SUBMIT DEBUG] step=provider_found status={provider.status} "
        f"is_active={provider.is_active} waba_id_present={bool(provider.waba_id)}"
    )

    if provider.status != "connected":
        raise TemplateSubmitError("Ative uma conexão Meta conectada antes de enviar templates.", 422)
    if not provider.waba_id:
        raise TemplateSubmitError("Provider não possui WABA ID configurado.", 422)

    token = decrypt_secret(provider.access_token_encrypted)
    if not token:
        raise TemplateSubmitError("Token Meta inválido ou expirado.", 401)

    try:
        print(
            f"[SUBMIT DEBUG] step=build_meta_payload template_name={template.name} "
            f"category={template.category} language={template.language}"
        )
        print(f"[SUBMIT DEBUG] step=meta_request endpoint=/{provider.waba_id}/message_templates")
        resp = asyncio.run(_submit_meta_template(template, provider, token, str(tenant_id)))
        template.status = "pending"
        template.submitted_at = datetime.utcnow()
        template.external_template_id = resp.get("id")
        template.metadata_json = {**(template.metadata_json or {}), "meta_submit_response": resp}
        db.commit()
        db.refresh(template)
        return template
    except MetaApiError as exc:
        status_code = int(getattr(exc, "status_code", 500) or 500)
        response_body = getattr(exc, "response_body", {}) or {}
        meta_error = response_body.get("error", {}) if isinstance(response_body, dict) else {}
        meta_message = meta_error.get("message") if isinstance(meta_error, dict) else str(exc)
        meta_code = meta_error.get("code") if isinstance(meta_error, dict) else None
        print(
            f"[SUBMIT DEBUG] step=meta_response status_code={status_code} "
            f"body={str(response_body)[:1500]}"
        )
        template.metadata_json = {**(template.metadata_json or {}), "last_error": str(exc)}
        db.commit()
        if status_code in {401, 403}:
            raise TemplateSubmitError("Token Meta inválido ou expirado.", 422, meta_error=meta_message, meta_code=meta_code) from exc
        if status_code == 404:
            raise TemplateSubmitError("Meta não encontrou o WABA informado.", 422, meta_error=meta_message, meta_code=meta_code) from exc
        raise TemplateSubmitError("Erro ao enviar template para Meta.", 422, meta_error=meta_message, meta_code=meta_code) from exc


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
        "name": (template.name or "").lower(),
        "language": "pt_BR",
        "category": (template.category or "UTILITY").upper(),
        "components": _build_components(template),
    }
    logger.info(
        "[WHATSAPP TEMPLATE META PAYLOAD] tenant_id=%s provider_id=%s template_id=%s template_name=%s category=%s body=%s",
        tenant_id,
        str(provider.id),
        str(template.id),
        template.name,
        (template.category or "UTILITY").upper(),
        template.body_text,
    )
    payload_name = (template.name or "").lower()
    payload_category = (template.category or "UTILITY").upper()
    payload_body = template.body_text
    print(
        f"[WHATSAPP TEMPLATE META PAYLOAD] name={payload_name} "
        f"language=pt_BR category={payload_category} body={payload_body}"
    )
    logger.info("[WHATSAPP TEMPLATE META PAYLOAD_FULL] payload=%s", payload)
    response = await client.post(f"/{provider.waba_id}/message_templates", payload=payload, context={"tenant_id": tenant_id, "provider_id": str(provider.id), "template_id": str(template.id)})
    print(f"[SUBMIT DEBUG] step=meta_response status_code=200 body={str(response)[:1500]}")
    return response


async def _list_meta_templates(provider: TenantWhatsAppProvider, token: str, tenant_id: str) -> dict:
    client = MetaCloudClient(token)
    return await client.get(f"/{provider.waba_id}/message_templates", context={"tenant_id": tenant_id, "provider_id": str(provider.id)})


def _build_components(template: WhatsAppMessageTemplate) -> list[dict]:
    body_component: dict = {"type": "BODY", "text": template.body_text}
    body_examples = _build_body_examples(template)
    if body_examples:
        body_component["example"] = {"body_text": [body_examples]}

    components = [body_component]
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


def _build_body_examples(template: WhatsAppMessageTemplate) -> list[str]:
    body_text = template.body_text or ""
    indexes = sorted({int(match) for match in re.findall(r"\{\{(\d+)\}\}", body_text)})
    if not indexes:
        return []

    default_examples = {1: "Gabriel", 2: "#4821", 3: "Exemplo 3"}
    variables_json = template.variables_json if isinstance(template.variables_json, list) else []
    example_map: dict[int, str] = {}

    for item in variables_json:
        if not isinstance(item, dict):
            continue
        idx = item.get("index") or item.get("position") or item.get("id")
        key = item.get("key")
        sample = item.get("example") or item.get("sample") or item.get("value")
        if isinstance(idx, int) and sample:
            example_map[idx] = str(sample)
            continue
        if isinstance(key, str) and key.isdigit() and sample:
            example_map[int(key)] = str(sample)

    return [example_map.get(i) or default_examples.get(i) or f"Exemplo {i}" for i in indexes]


def _resolve_provider(db: Session, tenant_id: UUID, provider_id: UUID | None):
    query = select(TenantWhatsAppProvider).where(TenantWhatsAppProvider.tenant_id == tenant_id, TenantWhatsAppProvider.provider_type == "meta_cloud")
    if provider_id:
        query = query.where(TenantWhatsAppProvider.id == provider_id)
    return db.execute(query).scalars().first()


def _resolve_provider_for_submit(db: Session, tenant_id: UUID, template: WhatsAppMessageTemplate):
    if template.provider_id:
        provider = _resolve_provider(db, tenant_id, template.provider_id)
        if provider:
            return provider
        raise TemplateSubmitError("Provider associado não encontrado.", 422)

    connected = db.execute(
        select(TenantWhatsAppProvider).where(
            TenantWhatsAppProvider.tenant_id == tenant_id,
            TenantWhatsAppProvider.provider_type == "meta_cloud",
            TenantWhatsAppProvider.status == "connected",
        )
    ).scalars().all()
    if len(connected) == 1:
        if not template.provider_id:
            template.provider_id = connected[0].id
        return connected[0]
    if len(connected) > 1:
        raise TemplateSubmitError("Selecione um provider para este template.", 422)

    active = db.execute(
        select(TenantWhatsAppProvider).where(
            TenantWhatsAppProvider.tenant_id == tenant_id,
            TenantWhatsAppProvider.provider_type == "meta_cloud",
            TenantWhatsAppProvider.is_active.is_(True),
        )
    ).scalars().first()
    if active:
        if not template.provider_id:
            template.provider_id = active.id
            db.commit()
            db.refresh(template)
        return active
    raise TemplateSubmitError("Ative uma conexão Meta conectada antes de enviar templates.", 422)


def _get_template(db: Session, tenant_id: UUID, template_id: UUID, raise_not_found: bool = False):
    template = db.execute(select(WhatsAppMessageTemplate).where(WhatsAppMessageTemplate.id == template_id, WhatsAppMessageTemplate.tenant_id == tenant_id)).scalars().first()
    if not template and raise_not_found:
        raise TemplateSubmitError("Template não encontrado para este tenant.", 404)
    return template
