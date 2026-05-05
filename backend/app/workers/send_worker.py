from __future__ import annotations

import logging
import uuid
from typing import Any

from app.db.session import SessionLocal
from app.models import Tenant
from app.services.whatsapp_service import send_whatsapp_interactive_buttons, send_whatsapp_message

logger = logging.getLogger(__name__)


def send_whatsapp_message(*, message_data: dict[str, Any]) -> None:
    tenant_id = str(message_data.get("tenant_id") or "")
    phone = str(message_data.get("phone") or "")
    text = str(message_data.get("text") or "").strip()
    buttons = message_data.get("buttons")

    tenant_uuid = uuid.UUID(tenant_id)
    with SessionLocal() as db:
        tenant = db.query(Tenant).filter(Tenant.id == tenant_uuid).first()
        if not tenant:
            logger.warning(
                "event=queue_send_skip reason=tenant_not_found tenant_id=%s phone=%s",
                tenant_id,
                phone,
            )
            return

        if buttons:
            send_whatsapp_interactive_buttons(
                tenant=tenant,
                phone=phone,
                body_text=text,
                buttons=buttons,
            )
        else:
            send_whatsapp_message(tenant=tenant, phone=phone, text=text)

        logger.info(
            "event=queue_send_success tenant_id=%s phone=%s text_len=%s has_buttons=%s",
            tenant_id,
            phone,
            len(text),
            bool(buttons),
        )
