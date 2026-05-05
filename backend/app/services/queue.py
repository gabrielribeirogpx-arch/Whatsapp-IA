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
from app.models import FailedMessage, Tenant

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SEND_QUEUE_NAME = os.getenv("WHATSAPP_SEND_QUEUE", "default")


INCOMING_QUEUE_NAME = os.getenv("INCOMING_MESSAGE_QUEUE", "default")


def get_queue(name: str | None = None) -> Queue:
    redis_conn = Redis.from_url(REDIS_URL, decode_responses=True)
    return Queue(name=name or SEND_QUEUE_NAME, connection=redis_conn)


def enqueue_incoming_message(payload: dict[str, Any]) -> str:
    correlation_id = str(payload.get("message_id") or payload.get("correlation_id") or "") or None
    tenant_hint = payload.get("tenant_id") or payload.get("tenant_hint")
    job = get_queue(INCOMING_QUEUE_NAME).enqueue(
        "app.workers.message_worker.process_incoming_message",
        payload,
    )
    logger.info(
        "event=incoming_message_enqueued correlation_id=%s tenant_hint=%s job_id=%s",
        correlation_id,
        tenant_hint,
        job.id,
    )
    return str(job.id)



def _record_failed_message(
    *,
    tenant_id: str,
    phone: str,
    text: str,
    buttons: list[dict[str, Any]] | None,
    job_id: str | None,
    error: str,
) -> None:
    try:
        tenant_uuid = uuid.UUID(str(tenant_id))
    except (TypeError, ValueError):
        logger.warning("[QUEUE FAILED] could not parse tenant_id for dead letter tenant_id=%s", tenant_id)
        return

    with SessionLocal() as db:
        failed = FailedMessage(
            tenant_id=tenant_uuid,
            phone=phone,
            text=text,
            buttons=buttons,
            error=error[:2000],
            job_id=job_id,
        )
        db.add(failed)
        db.commit()


def _on_send_failure(job, connection, type_, value, traceback) -> None:  # noqa: ANN001
    retries_left = getattr(job, "retries_left", None)
    if retries_left not in (None, 0):
        return

    message_data = job.kwargs.get("message_data", {}) if hasattr(job, "kwargs") else {}
    tenant_id = str(message_data.get("tenant_id") or "")
    phone = str(message_data.get("phone") or "")
    text = str(message_data.get("text") or "")
    buttons = message_data.get("buttons")
    error = f"{type_.__name__}: {value}" if type_ else str(value)

    _record_failed_message(
        tenant_id=str(tenant_id),
        phone=str(phone),
        text=str(text),
        buttons=buttons if isinstance(buttons, list) else None,
        job_id=getattr(job, "id", None),
        error=error,
    )
    print("[QUEUE FAILED]", error)
    logger.error(
        "[QUEUE FAILED] tenant_id=%s phone=%s job_id=%s error=%s",
        tenant_id,
        phone,
        getattr(job, "id", None),
        error,
    )


def enqueue_send_message(message_data: dict[str, Any]) -> str | None:
    tenant_id = message_data.get("tenant_id")
    phone = str(message_data.get("phone") or "")
    content = str(message_data.get("text") or "").strip()
    buttons = message_data.get("buttons")

    if not content:
        logger.warning("event=queue_send_skip reason=empty_text tenant_id=%s phone=%s", tenant_id, phone)
        return None

    if not phone:
        logger.warning("event=queue_send_skip reason=missing_phone tenant_id=%s", tenant_id)
        return None

    queue = get_queue(SEND_QUEUE_NAME)

    payload = {
        "tenant_id": str(tenant_id),
        "phone": phone,
        "text": content,
        "buttons": buttons if isinstance(buttons, list) else None,
    }

    job = queue.enqueue(
        "app.workers.send_worker.send_whatsapp_message",
        message_data=payload,
        retry=Retry(max=3, interval=[5, 15, 45]) if Retry else None,
        job_timeout=90,
        failure_ttl=86400,
        result_ttl=3600,
        on_failure=_on_send_failure,
    )

    logger.info(
        "event=queue_send_enqueued tenant_id=%s phone=%s job_id=%s has_buttons=%s",
        tenant_id,
        phone,
        job.id,
        bool(payload["buttons"]),
    )
    return str(job.id)
