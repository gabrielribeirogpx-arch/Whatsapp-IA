from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from app.observability import TraceContext, TraceEventType, record_event, sanitize_metadata
from app.observability.event_types import SUPPORTED_EVENT_TYPES
from app.observability.timeline_builder import build_execution_timeline


def test_trace_context_creation_keeps_required_ids():
    trace = TraceContext.from_mapping({"tenant_id": "tenant", "conversation_id": "conversation", "contact_id": "contact", "flow_id": "flow"})

    assert trace.trace_id
    assert trace.execution_id
    assert trace.tenant_id == "tenant"
    assert trace.conversation_id == "conversation"
    assert trace.contact_id == "contact"
    assert trace.flow_id == "flow"


def test_supported_event_types_include_enterprise_timeline_events():
    assert TraceEventType.WEBHOOK_RECEIVED.value in SUPPORTED_EVENT_TYPES
    assert TraceEventType.NODE_FAILED.value in SUPPORTED_EVENT_TYPES
    assert TraceEventType.MCP_FINISHED.value in SUPPORTED_EVENT_TYPES
    assert TraceEventType.EXECUTION_FAILED.value in SUPPORTED_EVENT_TYPES


def test_metadata_sanitization_redacts_secrets_and_full_prompts():
    sanitized = sanitize_metadata({
        "Authorization": "Bearer secret",
        "api_key": "secret",
        "cookie": "abc",
        "embedding": [0.1, 0.2],
        "prompt": "full prompt",
        "message": "full user message",
        "safe": "ok",
    })

    assert sanitized["Authorization"] == "[REDACTED]"
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["cookie"] == "[REDACTED]"
    assert sanitized["embedding"] == "[REDACTED]"
    assert sanitized["prompt"] == "[REDACTED]"
    assert sanitized["message"] == "[REDACTED]"
    assert sanitized["safe"] == "ok"


def test_record_event_without_db_is_non_blocking():
    record_event(None, TraceContext(trace_id="trace", execution_id="execution"), TraceEventType.JOB_ENQUEUED, metadata={"token": "secret"})


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return self

    def __iter__(self):
        return iter(self._rows)


class _FakeDb:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, _statement):
        return _ScalarResult(self._rows)


def test_timeline_builder_orders_and_summarizes_events():
    started = datetime.utcnow()
    rows = [
        SimpleNamespace(event_type="WEBHOOK_RECEIVED", timestamp=started, created_at=started, duration_ms=None, metadata_json={"step": 1}),
        SimpleNamespace(event_type="EXECUTION_FINISHED", timestamp=started + timedelta(milliseconds=250), created_at=started + timedelta(milliseconds=250), duration_ms=250, metadata_json={"ok": True}),
    ]

    timeline = build_execution_timeline(_FakeDb(rows), "trace-1")

    assert timeline["trace_id"] == "trace-1"
    assert timeline["duration_ms"] == 250
    assert [event["event_type"] for event in timeline["events"]] == ["WEBHOOK_RECEIVED", "EXECUTION_FINISHED"]
