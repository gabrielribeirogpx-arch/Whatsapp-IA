from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from redis import Redis
from rq import Queue, get_current_job

try:
    from rq import Retry
except ImportError:
    Retry = None

from app.db.session import SessionLocal
from app.models import FailedMessage, Tenant
from app.services.whatsapp_service import send_whatsapp_interactive_buttons, send_whatsapp_message

logger = logging.getLogger(__name__)

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SEND_QUEUE_NAME = os.getenv("WHATSAPP_SEND_QUEUE", "default")


def _send_whatsapp_job(tenant_id: str, phone: str, text: str, buttons: list[dict[str, Any]] | None = None) -> None:
    job = get_current_job()
    print("[RQ JOB] processing...")
    logger.info("[RQ JOB] processing job_id=%s", getattr(job, "id", None))

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
            len(text or ""),
            bool(buttons),
        )


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

    tenant_id = (job.args[0] if len(job.args) > 0 else "") or ""
    phone = (job.args[1] if len(job.args) > 1 else "") or ""
    text = (job.args[2] if len(job.args) > 2 else "") or ""
    buttons = job.args[3] if len(job.args) > 3 else None
    error = f"{type_.__name__}: {value}" if type_ else str(value)

    _record_failed_message(
        tenant_id=str(tenant_id),
        phone=str(phone),
        text=str(text),
        buttons=buttons if isinstance(buttons, list) else None,
        job_id=getattr(job, "id", None),
        error=error,
    )
    logger.error(
        "[QUEUE FAILED] tenant_id=%s phone=%s job_id=%s error=%s",
        tenant_id,
        phone,
        getattr(job, "id", None),
        error,
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
        on_failure=_on_send_failure,
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
