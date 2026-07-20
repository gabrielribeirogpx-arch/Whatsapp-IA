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


class ObservabilityService:
    """Best-effort façade for producers that need trace/span lifecycle calls.

    All persistence errors are contained in ``record_event`` so a webhook or
    worker continues even when the observability database path is unavailable.
    """
    def start_trace(self, db: "Session" | None, context: TraceContext | dict[str, Any] | None = None, **metadata: Any) -> TraceContext:
        trace = context if isinstance(context, TraceContext) else TraceContext.from_mapping(context or {})
        record_event(db, trace, TraceEventType.WEBHOOK_RECEIVED, metadata=metadata)
        return trace

    def finish_trace(self, db: "Session" | None, trace: TraceContext, *, duration_ms: int | None = None, **metadata: Any) -> None:
        record_event(db, trace, TraceEventType.EXECUTION_FINISHED, duration_ms=duration_ms, metadata=metadata)

    def fail_trace(self, db: "Session" | None, trace: TraceContext, *, error: Exception | str | None = None, duration_ms: int | None = None, **metadata: Any) -> None:
        metadata["error_type"] = type(error).__name__ if isinstance(error, Exception) else "Error"
        record_event(db, trace, TraceEventType.EXECUTION_FAILED, duration_ms=duration_ms, metadata=metadata)

    def record_event(self, db: "Session" | None, trace: TraceContext, event_type: TraceEventType | str, **kwargs: Any) -> None:
        record_event(db, trace, event_type, **kwargs)

    start_span = record_event
    finish_span = record_event
    fail_span = record_event

    def increment_metric(self, db: "Session" | None, trace: TraceContext, metric_name: str, value: int | float = 1, **dimensions: Any) -> None:
        self.record_event(db, trace, "METRIC_INCREMENT", metadata={"metric_name": metric_name, "value": value, **dimensions})

    def record_duration(self, db: "Session" | None, trace: TraceContext, metric_name: str, duration_ms: int, **dimensions: Any) -> None:
        self.record_event(db, trace, "METRIC_DURATION", duration_ms=duration_ms, metadata={"metric_name": metric_name, **dimensions})


observability_service = ObservabilityService()


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
