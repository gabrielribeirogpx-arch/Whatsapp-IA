from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.integrations.meta.meta_cloud_client import MetaApiError, MetaCloudClient
from app.models.tenant_whatsapp_provider import TenantWhatsAppProvider
from app.models.whatsapp_message_template import WhatsAppMessageTemplate
from app.utils.encryption import decrypt_secret
from app.services.message_origin_trace import log_message_origin_trace

logger = logging.getLogger(__name__)
VAR_PATTERN = re.compile(r"\{\{\s*(\d+)\s*\}\}")


def _provider_resolution_row(provider: TenantWhatsAppProvider) -> dict[str, Any]:
    return {
        "provider_id": str(provider.id),
        "tenant_id": str(provider.tenant_id),
        "is_active": provider.is_active,
        "status": provider.status,
        "updated_at": provider.updated_at.isoformat() if provider.updated_at else None,
    }


def _log_related_meta_provider_resolution(
    db: Session,
    *,
    provider: TenantWhatsAppProvider,
    tenant_id: str,
    conversation_id: str | None,
) -> None:
    phone_number_id = str(provider.phone_number_id or "").strip()
    waba_id = str(provider.waba_id or "").strip()
    business_id = str(provider.business_id or "").strip()
    clauses = []
    if phone_number_id:
        clauses.append(TenantWhatsAppProvider.phone_number_id == phone_number_id)
    if waba_id:
        clauses.append(TenantWhatsAppProvider.waba_id == waba_id)
    if business_id:
        clauses.append(TenantWhatsAppProvider.business_id == business_id)

    related_providers: list[TenantWhatsAppProvider] = []
    if clauses:
        related_providers = (
            db.execute(
                select(TenantWhatsAppProvider)
                .where(TenantWhatsAppProvider.provider_type == "meta_cloud", or_(*clauses))
                .order_by(TenantWhatsAppProvider.updated_at.desc())
            )
            .scalars()
            .all()
        )

    logger.info(
        "[PROVIDER RESOLUTION] tenant_id=%s conversation_id=%s selected_provider_id=%s same_phone_number_id=%s same_waba_id=%s same_business_id=%s",
        tenant_id,
        conversation_id or "n/a",
        provider.id,
        [_provider_resolution_row(item) for item in related_providers if phone_number_id and item.phone_number_id == phone_number_id],
        [_provider_resolution_row(item) for item in related_providers if waba_id and item.waba_id == waba_id],
        [_provider_resolution_row(item) for item in related_providers if business_id and item.business_id == business_id],
    )


def resolve_active_meta_provider_credentials(db: Session, *, tenant_id: str, conversation_id: str | None = None) -> dict[str, str] | None:
    providers = (
        db.execute(
            select(TenantWhatsAppProvider)
            .where(
                TenantWhatsAppProvider.tenant_id == tenant_id,
                TenantWhatsAppProvider.provider_type == "meta_cloud",
            )
            .order_by(TenantWhatsAppProvider.is_active.desc(), TenantWhatsAppProvider.updated_at.desc())
        )
        .scalars()
        .all()
    )
    active_providers = [provider for provider in providers if provider.is_active]
    logger.info(
        "[PROVIDER RESOLUTION] tenant_id=%s conversation_id=%s provider_count=%s active_count=%s providers=%s",
        tenant_id,
        conversation_id or "n/a",
        len(providers),
        len(active_providers),
        [
            {
                "provider_id": str(provider.id),
                "provider_name": provider.display_name,
                "is_active": provider.is_active,
                "status": provider.status,
                "phone_number_id": provider.phone_number_id,
                "waba_id": provider.waba_id,
                "business_id": provider.business_id,
                "updated_at": provider.updated_at.isoformat() if provider.updated_at else None,
            }
            for provider in providers
        ],
    )

    provider = active_providers[0] if active_providers else None
    if providers and not provider:
        logger.warning(
            "[PROVIDER RESOLUTION] tenant_id=%s conversation_id=%s provider_id=%s reason=no_active_meta_provider",
            tenant_id,
            conversation_id or "n/a",
            None,
        )
    logger.info(
        "[PROVIDER RESOLUTION] tenant_id=%s conversation_id=%s provider_id=%s phone_number_id=%s waba_id=%s business_id=%s",
        tenant_id,
        conversation_id or "n/a",
        str(provider.id) if provider else None,
        provider.phone_number_id if provider else None,
        provider.waba_id if provider else None,
        provider.business_id if provider else None,
    )
    if not provider:
        return None

    token = decrypt_secret(provider.access_token_encrypted or "")
    _log_related_meta_provider_resolution(db, provider=provider, tenant_id=tenant_id, conversation_id=conversation_id)
    logger.info(
        "[META TOKEN SOURCE] provider_id=%s token_length=%s source=%s",
        provider.id,
        len(token or ""),
        "provider",
    )
    if not token or not provider.phone_number_id:
        return None

    return {
        "provider_id": str(provider.id),
        "tenant_id": str(provider.tenant_id),
        "provider_name": str(provider.display_name or provider.provider_type),
        "token": token,
        "token_length": str(len(token)),
        "phone_number_id": str(provider.phone_number_id),
        "waba_id": str(provider.waba_id or ""),
        "business_id": str(provider.business_id or ""),
        "status": str(provider.status),
        "is_active": str(provider.is_active),
        "updated_at": provider.updated_at.isoformat() if provider.updated_at else "",
    }


def mark_provider_auth_error(db: Session, *, provider_id: str, error_message: str) -> None:
    provider = db.execute(select(TenantWhatsAppProvider).where(TenantWhatsAppProvider.id == provider_id)).scalars().first()
    if not provider:
        return
    provider.status = "token_expired"
    provider.metadata_json = {**(provider.metadata_json or {}), "last_error": error_message}
    db.add(provider)
    db.commit()


def send_text_message_via_meta(*, token: str, phone_number_id: str, to: str, text: str, context: dict[str, Any]) -> dict[str, Any]:
    log_message_origin_trace(
        executor=context.get("flow_executor") or context.get("flow_send_source") or "send_text_message_via_meta",
        flow_id=context.get("flow_id"),
        node_id=context.get("node_id"),
        node_type=context.get("node_type"),
        message=text,
        context=context,
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": re.sub(r"\D", "", to or ""),
        "type": "text",
        "text": {"body": text},
    }
    return asyncio.run(MetaCloudClient(token).post(f"/{phone_number_id}/messages", payload=payload, context=context))


def send_buttons_message_via_meta(*, token: str, phone_number_id: str, to: str, body_text: str, buttons: list[dict[str, Any]], context: dict[str, Any]) -> dict[str, Any]:
    log_message_origin_trace(
        executor=context.get("flow_executor") or context.get("flow_send_source") or "send_buttons_message_via_meta",
        flow_id=context.get("flow_id"),
        node_id=context.get("node_id"),
        node_type=context.get("node_type"),
        message=body_text,
        context=context,
    )
    safe_buttons = [
        {
            "type": "reply",
            "reply": {
                "id": str(btn.get("label") or "").strip().lower(),
                "title": str(btn.get("label") or "")[:20],
            },
        }
        for btn in buttons[:3]
        if isinstance(btn, dict) and str(btn.get("label") or "").strip()
    ]
    if not safe_buttons:
        return send_text_message_via_meta(token=token, phone_number_id=phone_number_id, to=to, text=body_text, context=context)

    payload = {
        "messaging_product": "whatsapp",
        "to": re.sub(r"\D", "", to or ""),
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body_text},
            "action": {"buttons": safe_buttons},
        },
    }
    logger.info(
        "[META INTERACTIVE PAYLOAD] flow_id=%s session_id=%s node_id=%s node_type=%s message_type=%s options_count=%s payload_json=%s",
        context.get("flow_id"),
        context.get("session_id"),
        context.get("node_id"),
        context.get("node_type"),
        payload.get("type"),
        len(safe_buttons),
        json.dumps(payload, default=str, ensure_ascii=False, sort_keys=True),
    )
    return asyncio.run(MetaCloudClient(token).post(f"/{phone_number_id}/messages", payload=payload, context=context))



def send_interactive_list_via_meta(*, token: str, phone_number_id: str, to: str, body_text: str, sections: list[dict[str, Any]], context: dict[str, Any], button_text: str = "Ver opções") -> dict[str, Any]:
    log_message_origin_trace(
        executor=context.get("flow_executor") or context.get("flow_send_source") or "send_interactive_list_via_meta",
        flow_id=context.get("flow_id"),
        node_id=context.get("node_id"),
        node_type=context.get("node_type"),
        message=body_text,
        context=context,
    )
    safe_sections: list[dict[str, Any]] = []
    for section_index, section in enumerate(sections or []):
        if not isinstance(section, dict):
            continue
        rows: list[dict[str, Any]] = []
        raw_rows = section.get("rows") if isinstance(section.get("rows"), list) else []
        for row_index, row in enumerate(raw_rows):
            if not isinstance(row, dict):
                continue
            title = str(row.get("title") or row.get("label") or "").strip()[:24]
            if not title:
                continue
            rows.append({
                "id": str(row.get("id") or row.get("handleId") or f"row_{section_index + 1}_{row_index + 1}"),
                "title": title,
                **({"description": str(row.get("description") or "")[:72]} if str(row.get("description") or "").strip() else {}),
            })
        if rows:
            safe_sections.append({"title": str(section.get("title") or f"Seção {section_index + 1}")[:24], "rows": rows})

    if not safe_sections:
        return send_text_message_via_meta(token=token, phone_number_id=phone_number_id, to=to, text=body_text, context=context)

    payload = {
        "messaging_product": "whatsapp",
        "to": re.sub(r"\D", "", to or ""),
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body_text},
            "action": {"button": (button_text or "Ver opções")[:20], "sections": safe_sections},
        },
    }
    logger.info(
        "[META INTERACTIVE PAYLOAD] flow_id=%s session_id=%s node_id=%s node_type=%s message_type=%s interactive_type=%s options_count=%s payload_json=%s",
        context.get("flow_id"),
        context.get("session_id"),
        context.get("node_id"),
        context.get("node_type"),
        payload.get("type"),
        "list",
        sum(len(section.get("rows") or []) for section in safe_sections),
        json.dumps(payload, default=str, ensure_ascii=False, sort_keys=True),
    )
    return asyncio.run(MetaCloudClient(token).post(f"/{phone_number_id}/messages", payload=payload, context=context))

def extract_template_variables(body_text: str) -> list[str]:
    return sorted({m.group(1) for m in VAR_PATTERN.finditer(body_text or "")}, key=lambda x: int(x))


def map_named_variables_to_meta_format(variables: dict[str, Any]) -> dict[str, str]:
    merged = dict(variables or {})
    first = str(merged.get("first_name") or "").strip()
    last = str(merged.get("last_name") or "").strip()
    if first and last and not merged.get("full_name"):
        merged["full_name"] = f"{first} {last}".strip()
    return {str(k): str(v) for k, v in merged.items() if v is not None}


def send_template_message(db: Session, *, tenant_id: str, provider_id: str, template_id: str, to: str, variables: dict[str, Any], language_code: str = "pt_BR") -> dict[str, Any]:
    provider = db.execute(select(TenantWhatsAppProvider).where(TenantWhatsAppProvider.id == provider_id, TenantWhatsAppProvider.tenant_id == tenant_id)).scalars().first()
    template = db.execute(select(WhatsAppMessageTemplate).where(WhatsAppMessageTemplate.id == template_id, WhatsAppMessageTemplate.tenant_id == tenant_id)).scalars().first()
    if not provider or not template:
        raise ValueError("Provider/template inválido para tenant.")

    token = decrypt_secret(provider.access_token_encrypted or "")
    if not token:
        raise ValueError("Token do provider ausente/inválido")

    varmap = map_named_variables_to_meta_format(variables)
    indexed = extract_template_variables(template.body_text)
    body_params = [{"type": "text", "text": varmap.get(v) or varmap.get(f"var_{v}") or ""} for v in indexed]
    components: list[dict[str, Any]] = [{"type": "body", "parameters": body_params}] if body_params else []

    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "template",
        "template": {"name": template.name, "language": {"code": language_code or template.language or "pt_BR"}, "components": components},
    }
    context = {"tenant_id": tenant_id, "provider_id": provider_id, "template_id": template_id, "token_length": len(token or ""), "executor": "send_template_message"}
    log_message_origin_trace(
        executor="send_template_message",
        flow_id=None,
        node_id=template_id,
        node_type="whatsapp_template",
        message=template.body_text,
        context=context,
    )
    client = MetaCloudClient(token)

    for attempt in range(1, 4):
        try:
            response = asyncio.run(client.post(f"/{provider.phone_number_id}/messages", payload=payload, context=context))
            message_id = (((response.get("messages") or [{}])[0]).get("id")) if isinstance(response, dict) else None
            logger.info("[WHATSAPP TEMPLATE SEND] tenant_id=%s provider_id=%s template_id=%s to=%s provider_message_id=%s", tenant_id, provider_id, template_id, to, message_id)
            return {"provider_message_id": message_id, "raw": response, "sent_at": datetime.utcnow()}
        except MetaApiError as exc:
            if attempt == 3:
                logger.error("[WHATSAPP TEMPLATE SEND ERROR] tenant_id=%s provider_id=%s template_id=%s to=%s status_code=%s error=%s", tenant_id, provider_id, template_id, to, exc.status_code, str(exc))
                raise
            asyncio.run(asyncio.sleep(2 ** attempt * 0.4))

    raise RuntimeError("Falha inesperada no envio de template")
