from __future__ import annotations

import json
import logging
import os
import subprocess
import traceback
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
from app.services.cache_service import check_rate_limit
from app.services.message_origin_trace import log_message_origin_trace

logger = logging.getLogger(__name__)


def _payload_summary(payload: Any, limit: int = 1200) -> str:
    try:
        encoded = json.dumps(payload, default=str, ensure_ascii=False, sort_keys=True)
    except Exception:
        encoded = str(payload)
    return encoded[:limit] + ("..." if len(encoded) > limit else "")


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
SEND_QUEUE_NAME = os.getenv("WHATSAPP_SEND_QUEUE", "normal")
INCOMING_QUEUE_NAME = os.getenv("INCOMING_MESSAGE_QUEUE", "high_priority")
LOW_PRIORITY_QUEUE_NAME = os.getenv("LOW_PRIORITY_QUEUE", "low")


def _runtime_commit() -> str:
    for env_name in (
        "API_COMMIT",
        "WORKER_COMMIT",
        "GIT_COMMIT",
        "RENDER_GIT_COMMIT",
        "RAILWAY_GIT_COMMIT_SHA",
        "VERCEL_GIT_COMMIT_SHA",
        "HEROKU_SLUG_COMMIT",
        "SOURCE_VERSION",
        "COMMIT_SHA",
    ):
        commit = str(os.getenv(env_name) or "").strip()
        if commit:
            return commit

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "--short=12", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return "unknown"

    return completed.stdout.strip() or "unknown"


def get_queue(name: str | None = None) -> Queue:
    redis_conn = Redis.from_url(REDIS_URL, decode_responses=True)
    return Queue(name=name or SEND_QUEUE_NAME, connection=redis_conn)


def enqueue_incoming_message(payload: dict[str, Any]) -> str:
    correlation_id = str(payload.get("correlation_id") or payload.get("message_id") or "n/a")
    tenant_hint = payload.get("tenant_id") or payload.get("tenant_hint") or "n/a"
    phone = str(payload.get("phone") or "n/a")
    tenant_for_limit = str(payload.get("tenant_id") or payload.get("tenant_hint") or "global")
    if not check_rate_limit(tenant_for_limit, max_per_minute=int(os.getenv("TENANT_RATE_LIMIT_PER_MINUTE", "180"))):
        logger.warning("event=rate_limit_exceeded tenant_id=%s stage=incoming_enqueue", tenant_for_limit)
        return "rate_limited"

    job = get_queue(INCOMING_QUEUE_NAME).enqueue(
        "app.workers.message_worker.process_incoming_message",
        payload,
    )
    logger.info(
        "event=incoming_message_enqueued correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=incoming_enqueue",
        correlation_id,
        tenant_hint,
        phone,
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
    sections = message_data.get("sections") if isinstance(message_data.get("sections"), list) else None
    options = message_data.get("options") if isinstance(message_data.get("options"), list) else None
    interactive_type = str(message_data.get("interactive_type") or ("button" if isinstance(buttons, list) and buttons else "")).strip().lower() or None
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
    correlation_id = str(message_data.get("correlation_id") or message_data.get("message_id") or "n/a")
    content = str(message_data.get("text") or "").strip()
    message_type_hint = str(message_data.get("message_type") or "").strip().lower()
    media_type = str(message_data.get("media_type") or "").strip().lower()
    media_url = str(message_data.get("media_url") or "").strip()
    buttons = message_data.get("buttons")
    sections = message_data.get("sections") if isinstance(message_data.get("sections"), list) else None
    options = message_data.get("options") if isinstance(message_data.get("options"), list) else None
    interactive_type = str(message_data.get("interactive_type") or ("button" if isinstance(buttons, list) and buttons else "")).strip().lower() or None

    is_media_message = message_type_hint == "media" or bool(media_type or media_url)
    if not content and not is_media_message:
        logger.warning("event=queue_send_skip correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=send_enqueue reason=empty_text", correlation_id, tenant_id, phone or "n/a", "n/a")
        return None
    if is_media_message and not content:
        content = str(message_data.get("caption") or "📎 Mídia enviada").strip() or "📎 Mídia enviada"

    if not phone:
        logger.warning("event=queue_send_skip correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=send_enqueue reason=missing_phone", correlation_id, tenant_id, "n/a", "n/a")
        return None

    queue = get_queue(SEND_QUEUE_NAME)

    passthrough_keys = (
        "flow_id",
        "flow_version_id",
        "session_id",
        "node_id",
        "sequence_number",
        "message_id",
        "node_type",
        "flow_engine",
        "flow_executor",
        "flow_send_source",
        "provider_id",
        "contact_id",
        "message_type",
        "media_type",
        "media_url",
        "caption",
        "filename",
    )
    metadata = message_data.get("metadata") if isinstance(message_data.get("metadata"), dict) else None
    payload = {
        "tenant_id": str(tenant_id or ""),
        "phone": phone,
        "text": content,
        "buttons": buttons if isinstance(buttons, list) else None,
        "sections": sections,
        "options": options,
        "interactive_type": interactive_type,
        "correlation_id": correlation_id,
        "conversation_id": str(message_data.get("conversation_id") or "") or None,
        "metadata": metadata,
        "message_type": "media" if is_media_message else None,
        "media_type": media_type or None,
        "media_url": media_url or None,
        "caption": str(message_data.get("caption") or "") or None,
        "filename": str(message_data.get("filename") or "") or None,
    }
    for key in passthrough_keys:
        value = message_data.get(key)
        if value is not None:
            payload[key] = str(value)

    logger.info(
        "[V2 ENQUEUE] normalized tenant_id=%s provider_id=%s session_id=%s conversation_id=%s contact_id=%s flow_id=%s phone=%s metadata_keys=%s",
        payload.get("tenant_id") or "",
        payload.get("provider_id"),
        payload.get("session_id"),
        payload.get("conversation_id"),
        payload.get("contact_id"),
        payload.get("flow_id"),
        phone,
        sorted(metadata.keys()) if metadata else [],
    )

    message_type = "media" if payload.get("message_type") == "media" else ("interactive" if payload.get("interactive_type") or (isinstance(payload.get("buttons"), list) and payload.get("buttons")) else "text")
    log_message_origin_trace(
        executor=payload.get("flow_executor") or payload.get("flow_send_source") or "enqueue_send_message",
        flow_id=payload.get("flow_id"),
        node_id=payload.get("node_id"),
        node_type=payload.get("node_type"),
        message=content,
        context=payload,
    )
    if payload.get("flow_id") or payload.get("node_id") or payload.get("flow_engine"):
        logger.warning(
            "[FLOW SEND ENQUEUE TRACE] engine=%s executor=%s source=%s flow_id=%s flow_version_id=%s session_id=%s node_id=%s node_type=%s message_type=%s text=%s stack=%s",
            payload.get("flow_engine") or "unknown",
            payload.get("flow_executor") or "unknown",
            payload.get("flow_send_source") or "enqueue_send_message",
            payload.get("flow_id"),
            payload.get("flow_version_id"),
            payload.get("session_id"),
            payload.get("node_id"),
            payload.get("node_type"),
            message_type,
            content,
            "".join(traceback.format_stack()),
        )
    logger.info(
        "[SEND WORKER MESSAGE TYPE] flow_id=%s session_id=%s node_id=%s node_type=%s message_type=%s options_count=%s payload_json=%s",
        payload.get("flow_id"),
        payload.get("session_id"),
        payload.get("node_id"),
        payload.get("node_type"),
        message_type,
        len(payload.get("options") or payload.get("buttons") or []) if isinstance(payload.get("options") or payload.get("buttons"), list) else 0,
        json.dumps(payload, default=str, ensure_ascii=False, sort_keys=True),
    )
    if payload.get("node_type") == "choice":
        logger.info(
            "[V2 CHOICE ENQUEUE] %s",
            json.dumps(
                {
                    "node_id": payload.get("node_id"),
                    "session_id": payload.get("session_id"),
                    "options_count": len(payload.get("options") or payload.get("buttons") or []) if isinstance(payload.get("options") or payload.get("buttons"), list) else 0,
                    "options": payload.get("options") or payload.get("buttons") or [],
                    "provider_id": payload.get("provider_id"),
                    "tenant_id": payload.get("tenant_id"),
                    "message_type": message_type,
                    "payload": payload,
                },
                default=str,
                ensure_ascii=False,
                sort_keys=True,
            ),
        )

    logger.info(
        "[FLOW QUEUE ENQUEUE] job_id=%s flow_id=%s session_id=%s node_id=%s sequence_number=%s message_text=%s api_commit=%s",
        "pending",
        payload.get("flow_id"),
        payload.get("session_id"),
        payload.get("node_id"),
        payload.get("sequence_number"),
        content,
        _runtime_commit(),
    )

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
        "[FLOW QUEUE ENQUEUE] job_id=%s flow_id=%s session_id=%s node_id=%s sequence_number=%s message_text=%s api_commit=%s",
        job.id,
        payload.get("flow_id"),
        payload.get("session_id"),
        payload.get("node_id"),
        payload.get("sequence_number"),
        content,
        _runtime_commit(),
    )

    if payload.get("interactive_type") == "list":
        logger.info(
            "[CHOICE LIST ENQUEUED] session_id=%s node_id=%s flow_id=%s interactive_type=%s job_id=%s options_count=%s payload_summary=%s",
            payload.get("session_id"),
            payload.get("node_id"),
            payload.get("flow_id"),
            payload.get("interactive_type"),
            job.id,
            len(payload.get("options") or []),
            _payload_summary({"text": payload.get("text"), "sections": payload.get("sections"), "options": payload.get("options")}),
        )

    logger.info(
        "event=queue_send_enqueued correlation_id=%s tenant_id=%s phone=%s job_id=%s stage=send_enqueue has_buttons=%s",
        correlation_id,
        tenant_id,
        phone,
        job.id,
        bool(payload.get("buttons") or payload.get("sections")),
    )
    return str(job.id)
