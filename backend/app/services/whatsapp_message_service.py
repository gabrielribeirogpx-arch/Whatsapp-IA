from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.integrations.meta.meta_cloud_client import MetaApiError, MetaCloudClient
from app.models.tenant_whatsapp_provider import TenantWhatsAppProvider
from app.models.whatsapp_message_template import WhatsAppMessageTemplate
from app.utils.encryption import decrypt_secret

logger = logging.getLogger(__name__)
VAR_PATTERN = re.compile(r"\{\{\s*(\d+)\s*\}\}")


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
    context = {"tenant_id": tenant_id, "provider_id": provider_id, "template_id": template_id}
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
