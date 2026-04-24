from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from redis import Redis
from rq import Queue

try:
    from rq import Retry
except ImportError:
    Retry = None

from app.db.session import SessionLocal
from app.models import Tenant
from app.services.whatsapp_service import send_whatsapp_interactive_buttons, send_whatsapp_message

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SEND_QUEUE_NAME = os.getenv("WHATSAPP_SEND_QUEUE", "whatsapp-send")



def _send_whatsapp_job(tenant_id: str, phone: str, text: str, buttons: list[dict[str, Any]] | None = None) -> None:
    tenant_uuid = uuid.UUID(str(tenant_id))
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
            try:
                send_whatsapp_interactive_buttons(
                    tenant=tenant,
                    phone=phone,
                    body_text=text,
                    buttons=buttons,
                )
            except Exception:
                logger.exception(
                    "event=queue_interactive_failed_fallback_text tenant_id=%s phone=%s",
                    tenant_id,
                    phone,
                )
                send_whatsapp_message(tenant=tenant, phone=phone, text=text)
        else:
            send_whatsapp_message(tenant=tenant, phone=phone, text=text)
        logger.info(
            "event=queue_send_success tenant_id=%s phone=%s text_len=%s has_buttons=%s",
            tenant_id,
            phone,
            len(text or ""),
            bool(buttons),
        )



def enqueue_send_message(
    tenant_id: uuid.UUID,
    phone: str,
    text: str,
    *,
    buttons: list[dict[str, Any]] | None = None,
) -> str | None:
    content = (text or "").strip()
    if not content:
        logger.warning("event=queue_send_skip reason=empty_text tenant_id=%s phone=%s", tenant_id, phone)
        return None

    if not phone:
        logger.warning("event=queue_send_skip reason=missing_phone tenant_id=%s", tenant_id)
        return None

    redis_conn = Redis.from_url(REDIS_URL, decode_responses=True)
    queue = Queue(name=SEND_QUEUE_NAME, connection=redis_conn)

    job = queue.enqueue(
        _send_whatsapp_job,
        str(tenant_id),
        phone,
        content,
        buttons,
        retry=Retry(max=3, interval=[5, 15, 45]) if Retry else None,
        failure_ttl=86400,
        result_ttl=3600,
    )

    logger.info("[QUEUE SEND] message enqueued")
    logger.info(
        "event=queue_send_enqueued tenant_id=%s phone=%s job_id=%s has_buttons=%s",
        tenant_id,
        phone,
        job.id,
        bool(buttons),
    )
    return str(job.id)
