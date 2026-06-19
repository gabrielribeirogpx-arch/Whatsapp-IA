from __future__ import annotations

import logging
import re
import uuid
from datetime import datetime
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

from app.observability.event_types import TraceEventType
from app.observability.trace_context import TraceContext

logger = logging.getLogger(__name__)
SENSITIVE_KEY_RE = re.compile(r"(authorization|bearer|api[-_]?key|apikey|secret|token|cookie|password|embedding|prompt|message|user[_-]?text|input_text|content|body)", re.I)
MAX_STRING_LENGTH = 500


def sanitize_metadata(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        safe = {}
        for key, item in value.items():
            key_str = str(key)
            safe[key_str] = "[REDACTED]" if SENSITIVE_KEY_RE.search(key_str) else sanitize_metadata(item, depth=depth + 1)
        return safe
    if isinstance(value, (list, tuple)):
        return [sanitize_metadata(item, depth=depth + 1) for item in list(value)[:50]]
    if isinstance(value, str):
        return value[:MAX_STRING_LENGTH] + ("..." if len(value) > MAX_STRING_LENGTH else "")
    return value


def _uuid_or_none(value: Any) -> uuid.UUID | None:
    if value in (None, ""):
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def record_event(
    db: "Session" | None,
    trace: TraceContext | dict[str, Any] | None,
    event_type: TraceEventType | str,
    *,
    duration_ms: int | None = None,
    metadata: dict[str, Any] | None = None,
    timestamp: datetime | None = None,
) -> None:
    event_name = event_type.value if isinstance(event_type, TraceEventType) else str(event_type)
    ctx = trace if isinstance(trace, TraceContext) else TraceContext.from_mapping(trace or {})
    safe_metadata = sanitize_metadata(metadata or {})
    if db is None:
        logger.info("observability_event trace_id=%s event_type=%s metadata=%s", ctx.trace_id, event_name, safe_metadata)
        return
    try:
        from app.models.execution_trace import ExecutionTrace

        db.add(ExecutionTrace(
            trace_id=ctx.trace_id,
            execution_id=ctx.execution_id,
            tenant_id=_uuid_or_none(ctx.tenant_id),
            conversation_id=_uuid_or_none(ctx.conversation_id),
            contact_id=_uuid_or_none(ctx.contact_id),
            flow_id=_uuid_or_none(ctx.flow_id),
            event_type=event_name,
            timestamp=timestamp or datetime.utcnow(),
            duration_ms=duration_ms,
            metadata_json=safe_metadata,
        ))
        # No commit here: piggyback on caller transaction to avoid commit-per-event.
    except Exception:
        logger.exception("failed_to_record_observability_event trace_id=%s event_type=%s", ctx.trace_id, event_name)
