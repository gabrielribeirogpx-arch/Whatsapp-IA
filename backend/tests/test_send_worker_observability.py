from __future__ import annotations

import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from app.observability import TraceContext, TraceEventType
from app.workers import send_worker


def test_send_worker_builds_trace_context_without_name_error() -> None:
    trace = send_worker._build_trace_context_best_effort(
        {"trace_id": "trace-1", "tenant_id": "tenant-payload"},
        tenant_id="tenant-override",
        conversation_id="conversation-1",
        flow_id="flow-1",
    )

    assert isinstance(trace, TraceContext)
    assert trace.trace_id == "trace-1"
    assert trace.tenant_id == "tenant-override"
    assert trace.conversation_id == "conversation-1"
    assert trace.flow_id == "flow-1"


def test_send_worker_observability_record_event_is_best_effort(monkeypatch) -> None:
    calls: list[tuple[object, object]] = []

    def fail_record_event(*args, **kwargs):
        calls.append((args, kwargs))
        raise RuntimeError("observability backend unavailable")

    monkeypatch.setattr(send_worker, "record_event", fail_record_event)

    send_worker._record_observability_event_best_effort(
        TraceContext(trace_id="trace-1"),
        TraceEventType.WORKER_STARTED,
        metadata={"job_id": "job-1"},
    )

    assert len(calls) == 1


def test_send_worker_trace_context_creation_is_best_effort(monkeypatch) -> None:
    def fail_from_mapping(*args, **kwargs):
        raise RuntimeError("invalid trace payload")

    monkeypatch.setattr(send_worker.TraceContext, "from_mapping", fail_from_mapping)

    trace = send_worker._build_trace_context_best_effort({"trace_id": "trace-1"})

    assert trace is None
