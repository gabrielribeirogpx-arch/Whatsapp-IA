from datetime import datetime, timedelta

from app.services.observability_reports.analyzer import analyse
from app.services.observability_reports.pdf_renderer import render_report


def _summary(executions=2):
    return {"executions": executions, "success_rate": 100, "error_rate": 0, "errors": 0, "retries": 0, "lock_contention": 0, "p50": 12, "p95": 30, "p99": 45, "throughput_per_minute": 1.2, "alerts_active": 0}


def test_executive_pdf_is_deterministic_and_uses_portuguese_labels():
    start = datetime(2026, 1, 1, 10)
    kwargs = dict(tenant={"id": "tenant-a", "name": "Organização"}, summary=_summary(), records=[], start=start, end=start + timedelta(hours=1), timezone_name="UTC")
    first = render_report(**kwargs)
    assert first == render_report(**kwargs)
    assert first.startswith(b"%PDF")
    assert b"Relat\xf3rio de Observabilidade" in first
    assert b"period_start" not in first


def test_insufficient_data_never_reports_healthy():
    health = analyse(_summary(executions=0))
    assert health.label == "Dados insuficientes"


def test_technical_trace_pdf_is_sanitized():
    start = datetime(2026, 1, 1, 10)
    data = render_report(tenant={"id": "tenant-a", "name": "Org"}, summary=_summary(), records=[{"trace_id": "trace-1", "execution_id": "run-1", "status": "success"}], start=start, end=start + timedelta(hours=1), timezone_name="UTC", mode="technical", trace=True, timeline_rows=[{"event_type": "WEBHOOK_RECEIVED", "timestamp": "2026-01-01", "duration_ms": 12, "status": "ok", "metadata": {"access_token": "[REDACTED]"}}])
    assert b"Timeline visual" in data
    assert b"access_token" not in data
