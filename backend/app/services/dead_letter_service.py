from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any

from app.db.session import SessionLocal
from app.models.worker_dead_letter import WorkerDeadLetter

logger = logging.getLogger(__name__)

_SENSITIVE_RE = re.compile(r"(token|secret|password|api[_-]?key|authorization|prompt|message|text|body|content)", re.I)
_MAX_STRING = 180


def sanitize_payload_summary(payload: Any, *, max_depth: int = 3) -> Any:
    if max_depth < 0:
        return "<redacted:depth>"
    if isinstance(payload, dict):
        out: dict[str, Any] = {}
        for key, value in payload.items():
            key_str = str(key)
            if _SENSITIVE_RE.search(key_str):
                out[key_str] = "<redacted>"
            else:
                out[key_str] = sanitize_payload_summary(value, max_depth=max_depth - 1)
        return out
    if isinstance(payload, (list, tuple)):
        return [sanitize_payload_summary(item, max_depth=max_depth - 1) for item in list(payload)[:20]]
    if isinstance(payload, str):
        if len(payload) > _MAX_STRING:
            return payload[:_MAX_STRING] + "..."
        return payload
    if isinstance(payload, (int, float, bool)) or payload is None:
        return payload
    return str(payload)[:_MAX_STRING]


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None


def record_dead_letter(
    job_type: str,
    tenant_id: Any = None,
    queue_name: str | None = None,
    reason: str | None = None,
    payload_summary: Any = None,
    metadata: dict[str, Any] | None = None,
) -> str | None:
    safe_payload = sanitize_payload_summary(payload_summary or {})
    safe_metadata = sanitize_payload_summary(metadata or {})
    row_id: str | None = None
    try:
        with SessionLocal() as db:
            row = WorkerDeadLetter(
                tenant_id=_uuid_or_none(tenant_id),
                job_type=str(job_type or "unknown")[:80],
                queue_name=str(queue_name or "")[:80] or None,
                reason=str(reason or "unknown")[:500],
                payload_summary=safe_payload,
                job_metadata=safe_metadata,
                created_at=datetime.utcnow(),
            )
            db.add(row)
            db.commit()
            row_id = str(row.id)
    except Exception:
        logger.exception("event=job_dead_letter_record_failed job_type=%s queue=%s", job_type, queue_name)
        return None
    logger.warning(
        "event=job_dead_lettered id=%s job_type=%s tenant_id=%s queue=%s reason=%s",
        row_id,
        job_type,
        tenant_id or "n/a",
        queue_name or "n/a",
        reason or "unknown",
    )
    return row_id
