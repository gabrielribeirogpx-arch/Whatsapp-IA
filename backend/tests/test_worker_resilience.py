from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.services import job_queue_service
from app.services.dead_letter_service import sanitize_payload_summary


def test_envelope_new_contains_schema_and_idempotency() -> None:
    envelope = job_queue_service.make_job_envelope(
        "inbound_message",
        {"tenant_id": "tenant-1", "message_id": "msg-1", "text": "hello"},
        trace_id="trace-1",
    )
    assert envelope["job_schema_version"] == job_queue_service.CURRENT_JOB_SCHEMA_VERSION
    assert envelope["job_type"] == "inbound_message"
    assert envelope["tenant_id"] == "tenant-1"
    assert envelope["idempotency_key"] == "msg-1"
    assert envelope["metadata"]["trace_id"] == "trace-1"


def test_legacy_payload_is_accepted() -> None:
    payload = {"tenant_id": "tenant-1", "text": "legacy"}
    assert job_queue_service.unwrap_job_envelope(payload, expected_job_type="inbound_message") is payload


def test_future_version_does_not_execute(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(job_queue_service, "record_dead_letter", lambda *args, **kwargs: calls.append((args, kwargs)) or "dlq-1")
    result = job_queue_service.unwrap_job_envelope(
        {"job_schema_version": 999, "job_type": "inbound_message", "tenant_id": "tenant-1", "payload": {"text": "secret"}},
        expected_job_type="inbound_message",
    )
    assert result is None
    assert calls and calls[0][0][3] == "future_job_schema_version"


def test_missing_tenant_for_critical_job_goes_to_dlq(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(job_queue_service, "record_dead_letter", lambda *args, **kwargs: calls.append((args, kwargs)) or "dlq-1")
    result = job_queue_service.unwrap_job_envelope(
        {"job_schema_version": 1, "job_type": "whatsapp_send", "tenant_id": None, "payload": {"phone": "551199"}},
        expected_job_type="whatsapp_send",
    )
    assert result is None
    assert calls and calls[0][0][3] == "missing_tenant_id"


def test_failure_handler_records_dlq(monkeypatch) -> None:
    calls = []
    monkeypatch.setattr(job_queue_service, "record_dead_letter", lambda *args, **kwargs: calls.append((args, kwargs)) or "dlq-1")
    job = SimpleNamespace(
        retries_left=0,
        id="job-1",
        origin="high_priority",
        kwargs={"payload": {"job_type": "inbound_message", "tenant_id": "tenant-1", "payload": {"text": "do not leak"}}},
    )
    job_queue_service.on_job_failure(job, None, RuntimeError, RuntimeError("boom secret-token"), None)
    assert calls
    assert calls[0][0][0] == "inbound_message"
    assert calls[0][0][1] == "tenant-1"


def test_inbound_retry_and_timeout_profile() -> None:
    profile = job_queue_service.JOB_PROFILES["inbound_message"]
    assert profile["timeout"] == 60
    assert profile["failure_ttl"] == 86400
    assert getattr(profile["retry"], "max", None) == 5


def test_sanitize_payload_summary_redacts_secrets() -> None:
    summary = sanitize_payload_summary({"token": "abc", "api_key": "def", "message": "full text", "safe": "ok"})
    assert summary["token"] == "<redacted>"
    assert summary["api_key"] == "<redacted>"
    assert summary["message"] == "<redacted>"
    assert summary["safe"] == "ok"
    assert "abc" not in str(summary)


def test_worker_rq_imports_with_signal_handler() -> None:
    import worker_rq  # noqa: F401


def test_reap_stuck_jobs_removes_unreadable_rq_job(monkeypatch, caplog) -> None:
    removed_from_registry = []
    removed_from_queue = []
    deleted_keys = []

    class FakeConnection:
        def delete(self, *keys):
            deleted_keys.extend(keys)

    class FakeJobClass:
        def __init__(self, id, connection=None, serializer=None):
            self.key = f"rq:job:{id}"

    class FakeQueue:
        job_class = FakeJobClass
        serializer = None

        def __init__(self, name, connection):
            self.name = name
            self.connection = connection

        def fetch_job(self, job_id):
            raise UnicodeDecodeError("utf-8", b"\x9c", 0, 1, "invalid start byte")

        def remove(self, job_id):
            removed_from_queue.append(job_id)

    class FakeRegistry:
        def __init__(self, queue):
            self.queue = queue

        def get_job_ids(self):
            return ["legacy-job"]

        def remove(self, job_id):
            removed_from_registry.append(job_id)

    monkeypatch.setattr(job_queue_service, "redis_connection", lambda: FakeConnection())
    monkeypatch.setattr(job_queue_service, "Queue", FakeQueue)
    monkeypatch.setattr(job_queue_service, "StartedJobRegistry", FakeRegistry)
    monkeypatch.setattr(job_queue_service, "FailedJobRegistry", lambda queue: SimpleNamespace(get_job_ids=lambda: []))
    monkeypatch.setattr(job_queue_service, "DeferredJobRegistry", lambda queue: SimpleNamespace(get_job_ids=lambda: []))

    with caplog.at_level("WARNING"):
        assert job_queue_service.reap_stuck_jobs(["default"]) == 0

    assert removed_from_registry == ["legacy-job"]
    assert removed_from_queue == ["legacy-job"]
    assert deleted_keys == ["rq:job:legacy-job"]
    assert "event=invalid_rq_job_removed" in caplog.text


def test_redis_realtime_broker_unsubscribe_cancels_sse_task(monkeypatch) -> None:
    from app.services.redis_realtime_service import RedisRealtimeBroker

    async def run_test() -> None:
        async def never_listen(channel, queue):
            await asyncio.Event().wait()

        broker = RedisRealtimeBroker()
        monkeypatch.setattr(broker, "_listen_to_redis", never_listen)

        queue = await broker.subscribe("dashboard:tenant-1")
        task = getattr(queue, "_redis_realtime_task")
        broker.unsubscribe("dashboard:tenant-1", queue)
        await asyncio.sleep(0)

        assert task.cancelled()

    asyncio.run(run_test())
