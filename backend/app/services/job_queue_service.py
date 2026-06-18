from __future__ import annotations

import logging
import os
import subprocess
import uuid
from datetime import UTC, datetime
from typing import Any

from redis import Redis
from rq import Queue
from rq.registry import DeferredJobRegistry, FailedJobRegistry, StartedJobRegistry

try:
    from rq import Retry
except ImportError:  # pragma: no cover
    Retry = None  # type: ignore[assignment]

from app.services.dead_letter_service import record_dead_letter, sanitize_payload_summary

logger = logging.getLogger(__name__)

CURRENT_JOB_SCHEMA_VERSION = 1
DEFAULT_JOB_TIMEOUT = 90
DEFAULT_RESULT_TTL = 3600
DEFAULT_FAILURE_TTL = 86400
DEFAULT_RETRY = Retry(max=3, interval=[5, 15, 45]) if Retry else None

JOB_PROFILES: dict[str, dict[str, Any]] = {
    "inbound_message": {"queue": os.getenv("INCOMING_MESSAGE_QUEUE", "high_priority"), "retry": Retry(max=5, interval=[2, 5, 15, 45, 120]) if Retry else None, "timeout": 60, "failure_ttl": 86400},
    "flow_execution": {"queue": os.getenv("FLOW_RUNTIME_QUEUE", "default"), "retry": DEFAULT_RETRY, "timeout": 120, "failure_ttl": 86400},
    "whatsapp_send": {"queue": os.getenv("WHATSAPP_SEND_QUEUE", "normal"), "retry": DEFAULT_RETRY, "timeout": 90, "failure_ttl": 86400},
    "delay": {"queue": os.getenv("LOW_PRIORITY_QUEUE", "low"), "retry": Retry(max=2, interval=[30, 120]) if Retry else None, "timeout": 180, "failure_ttl": 86400},
    "ai_long": {"queue": os.getenv("LOW_PRIORITY_QUEUE", "low"), "retry": Retry(max=2, interval=[15, 60]) if Retry else None, "timeout": 300, "failure_ttl": 86400},
}

CRITICAL_TENANT_JOB_TYPES = {"inbound_message", "flow_execution", "whatsapp_send", "delay"}


def build_version() -> str:
    for name in ("WORKER_COMMIT", "API_COMMIT", "GIT_COMMIT", "RENDER_GIT_COMMIT", "RAILWAY_GIT_COMMIT_SHA", "SOURCE_VERSION", "COMMIT_SHA"):
        value = str(os.getenv(name) or "").strip()
        if value:
            return value
    try:
        return subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], check=True, capture_output=True, text=True, timeout=2).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def redis_connection() -> Redis:
    return Redis.from_url(os.getenv("REDIS_URL", "redis://localhost:6379/0"), decode_responses=True)


def make_job_envelope(job_type: str, payload: dict[str, Any], *, tenant_id: Any = None, idempotency_key: str | None = None, trace_id: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    tenant = str(tenant_id or payload.get("tenant_id") or payload.get("tenant_hint") or "") or None
    key = idempotency_key or str(payload.get("idempotency_key") or payload.get("message_id") or payload.get("correlation_id") or uuid.uuid4())
    return {
        "job_schema_version": CURRENT_JOB_SCHEMA_VERSION,
        "job_type": job_type,
        "tenant_id": tenant,
        "idempotency_key": key,
        "created_at": datetime.now(UTC).isoformat(),
        "payload": payload,
        "metadata": {"source": metadata.get("source") if metadata else job_type, "build_version": build_version(), "trace_id": trace_id or str(payload.get("trace_id") or payload.get("correlation_id") or key), **(metadata or {})},
    }


def unwrap_job_envelope(raw: dict[str, Any], *, expected_job_type: str, queue_name: str | None = None) -> dict[str, Any] | None:
    if not isinstance(raw, dict) or "job_schema_version" not in raw:
        return raw
    version = int(raw.get("job_schema_version") or 0)
    tenant_id = raw.get("tenant_id")
    if version > CURRENT_JOB_SCHEMA_VERSION:
        record_dead_letter(expected_job_type, tenant_id, queue_name, "future_job_schema_version", sanitize_payload_summary(raw), {"job_schema_version": version})
        logger.warning("event=job_requeued_due_to_version job_type=%s tenant_id=%s job_schema_version=%s", expected_job_type, tenant_id or "n/a", version)
        return None
    if expected_job_type in CRITICAL_TENANT_JOB_TYPES and not tenant_id:
        record_dead_letter(expected_job_type, None, queue_name, "missing_tenant_id", sanitize_payload_summary(raw), {"job_schema_version": version})
        return None
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}
    payload.setdefault("tenant_id", tenant_id)
    payload.setdefault("idempotency_key", raw.get("idempotency_key"))
    meta = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    payload.setdefault("trace_id", meta.get("trace_id"))
    return payload


def enqueue_profiled_job(job_type: str, func: Any, *args: Any, payload: dict[str, Any] | None = None, on_failure: Any = None, **kwargs: Any):
    profile = JOB_PROFILES[job_type]
    queue = Queue(name=profile["queue"], connection=redis_connection())
    job_kwargs = dict(kwargs)
    if payload is not None:
        job_kwargs["payload"] = make_job_envelope(job_type, payload, tenant_id=payload.get("tenant_id"), trace_id=payload.get("trace_id") or payload.get("correlation_id"))
    job = queue.enqueue(func, *args, retry=profile["retry"], job_timeout=profile["timeout"], failure_ttl=profile["failure_ttl"], result_ttl=DEFAULT_RESULT_TTL, on_failure=on_failure or on_job_failure, **job_kwargs)
    logger.info("event=job_enqueued job_type=%s queue=%s tenant_id=%s trace_id=%s job_schema_version=%s build_version=%s job_id=%s", job_type, queue.name, (payload or {}).get("tenant_id") or "n/a", (payload or {}).get("trace_id") or (payload or {}).get("correlation_id") or "n/a", CURRENT_JOB_SCHEMA_VERSION, build_version(), job.id)
    return job


def on_job_failure(job, connection, type_, value, traceback) -> None:  # noqa: ANN001
    retries_left = getattr(job, "retries_left", None)
    if retries_left not in (None, 0):
        return
    raw = (getattr(job, "kwargs", {}) or {}).get("payload") or (getattr(job, "kwargs", {}) or {}).get("message_data") or {}
    job_type = raw.get("job_type") if isinstance(raw, dict) else None
    envelope = raw if isinstance(raw, dict) and "payload" in raw else {}
    tenant_id = envelope.get("tenant_id") or (raw.get("tenant_id") if isinstance(raw, dict) else None)
    record_dead_letter(str(job_type or getattr(job, "description", "unknown"))[:80], tenant_id, getattr(getattr(job, "origin", None), "name", None) or getattr(job, "origin", None), f"{getattr(type_, '__name__', 'Exception')}: {str(value)[:300]}", sanitize_payload_summary(raw), {"job_id": getattr(job, "id", None), "exc_type": getattr(type_, "__name__", None)})


def reap_stuck_jobs(queue_names: list[str] | None = None) -> int:
    max_age = int(os.getenv("WORKER_STUCK_JOB_MAX_AGE_SECONDS", "1800"))
    conn = redis_connection()
    names = queue_names or [p["queue"] for p in JOB_PROFILES.values()]
    count = 0
    for name in sorted(set(names)):
        queue = Queue(name=name, connection=conn)
        for registry_cls in (StartedJobRegistry, FailedJobRegistry, DeferredJobRegistry):
            registry = registry_cls(queue=queue)
            for job_id in registry.get_job_ids():
                job = queue.fetch_job(job_id)
                if not job:
                    continue
                age = (datetime.now(UTC) - (job.started_at or job.ended_at or job.created_at).replace(tzinfo=UTC)).total_seconds()
                if age >= max_age:
                    count += 1
                    logger.warning("event=stuck_job_detected queue=%s registry=%s job_id=%s age_seconds=%s", name, registry_cls.__name__, job_id, int(age))
                    record_dead_letter("stuck_job", None, name, "stuck_job_detected", {"job_id": job_id, "registry": registry_cls.__name__, "age_seconds": int(age)}, {})
    return count
