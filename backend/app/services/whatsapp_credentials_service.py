from __future__ import annotations

import logging
import os
import uuid

from app.db.session import SessionLocal
from app.models import Tenant

logger = logging.getLogger(__name__)


class WhatsAppCredentialsNotConfiguredError(RuntimeError):
    def __init__(self, tenant_id: str):
        super().__init__(f"[WHATSAPP NOT CONFIGURED] tenant_id={tenant_id}")
        self.tenant_id = tenant_id


def get_tenant_whatsapp_credentials(tenant_id: str) -> dict[str, str]:
    tenant_id = str(tenant_id or "").strip()
    if not tenant_id:
        raise WhatsAppCredentialsNotConfiguredError(tenant_id="")

    try:
        tenant_uuid = uuid.UUID(tenant_id)
    except (TypeError, ValueError) as exc:
        raise WhatsAppCredentialsNotConfiguredError(tenant_id=tenant_id) from exc

    with SessionLocal() as db:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_uuid).first()

    token = str(getattr(tenant, "whatsapp_token", "") or "").strip() if tenant else ""
    phone_number_id = str(getattr(tenant, "phone_number_id", "") or "").strip() if tenant else ""

    allow_fallback = str(os.getenv("ALLOW_GLOBAL_WHATSAPP_FALLBACK", "")).strip().lower() == "true"
    if token and phone_number_id:
        logger.info("[WHATSAPP SEND USING TENANT CREDENTIALS] tenant_id=%s phone_number_id=%s", tenant_id, phone_number_id)
        return {"token": token, "phone_number_id": phone_number_id}

    if allow_fallback:
        fallback_token = str(os.getenv("WHATSAPP_TOKEN") or "").strip()
        fallback_phone_number_id = (
            str(os.getenv("WHATSAPP_PHONE_NUMBER_ID") or "").strip()
            or str(os.getenv("PHONE_NUMBER_ID") or "").strip()
        )
        if fallback_token and fallback_phone_number_id:
            logger.warning("[GLOBAL WHATSAPP FALLBACK USED] tenant_id=%s", tenant_id)
            return {"token": fallback_token, "phone_number_id": fallback_phone_number_id}

    raise WhatsAppCredentialsNotConfiguredError(tenant_id=tenant_id)
