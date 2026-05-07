from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from app.db.session import SessionLocal
from app.models import Tenant
from app.services.whatsapp_service import (
    send_whatsapp_interactive_buttons,
    send_whatsapp_message as send_whatsapp_text_message,
)

logger = logging.getLogger(__name__)


def send_whatsapp_message(*, message_data: dict[str, Any]) -> None:
    tenant_id = str(message_data.get("tenant_id") or "")
    phone = str(message_data.get("phone") or "")
    text = str(message_data.get("text") or "").strip()
    buttons = message_data.get("buttons")
    correlation_id = str(message_data.get("correlation_id") or message_data.get("message_id") or "n/a")
    job_id = str(message_data.get("job_id") or "n/a")

    logger.info("event=send_worker_start correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=send_worker_start", correlation_id, tenant_id or "n/a", phone or "n/a", job_id)

    try:
        tenant_uuid = uuid.UUID(tenant_id)
    except (ValueError, TypeError):
        logger.error(
            "event=queue_send_error correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=send_worker_resolve reason=invalid_tenant_id",
            correlation_id,
            tenant_id or "n/a",
            phone or "n/a",
            job_id,
        )
        return

    with SessionLocal() as db:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_uuid).first()
        if not tenant:
            logger.warning(
                "event=queue_send_skip correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=send_worker_resolve reason=tenant_not_found",
                correlation_id,
                tenant_id,
                phone,
                job_id,
            )
            return

        tenant_phone_number_id = str(getattr(tenant, "phone_number_id", "") or "").strip()
        tenant_token = str(getattr(tenant, "whatsapp_token", "") or "").strip()

        resolved_phone_number_id = (
            tenant_phone_number_id
            or str(os.getenv("WHATSAPP_PHONE_NUMBER_ID") or "").strip()
            or str(os.getenv("PHONE_NUMBER_ID") or "").strip()
        )
        resolved_token = tenant_token or str(os.getenv("WHATSAPP_TOKEN") or "").strip()

        if not resolved_phone_number_id or not resolved_token:
            logger.error(
                "event=queue_send_error correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=send_worker_resolve reason=missing_whatsapp_credentials has_phone_number_id=%s has_token=%s",
                correlation_id,
                tenant_id,
                phone,
                job_id,
                bool(resolved_phone_number_id),
                bool(resolved_token),
            )
            return

        tenant.phone_number_id = resolved_phone_number_id
        tenant.whatsapp_token = resolved_token

        if buttons:
            send_whatsapp_interactive_buttons(
                phone=phone,
                body_text=text,
                buttons=buttons,
                token=resolved_token,
                phone_number_id=resolved_phone_number_id,
            )
        else:
            send_whatsapp_text_message(
                phone=phone,
                text=text,
                token=resolved_token,
                phone_number_id=resolved_phone_number_id,
            )

        logger.info(
            "event=queue_send_success correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=send_final text_len=%s has_buttons=%s",
            correlation_id,
            tenant_id,
            phone,
            job_id,
            len(text),
            bool(buttons),
        )
