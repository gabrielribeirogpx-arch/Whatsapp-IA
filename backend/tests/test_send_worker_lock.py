from __future__ import annotations

import json
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from app.workers import send_worker


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def set(self, key: str, value: str, *, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = value
        if ex is not None:
            self.ttls[key] = ex
        return True

    def get(self, key: str) -> str | None:
        return self.values.get(key)

    def ttl(self, key: str) -> int:
        if key not in self.values:
            return -2
        return self.ttls.get(key, -1)

    def delete(self, key: str) -> int:
        existed = key in self.values
        self.values.pop(key, None)
        self.ttls.pop(key, None)
        return int(existed)


def _lock_kwargs(job_id: str, token: str = "token") -> dict:
    return {
        "lock_key": "wa:send-lock:tenant-1:5511999999999",
        "lock_token": token,
        "tenant_id": "tenant-1",
        "phone": "5511999999999",
        "conversation_id": "conversation-1",
        "job_id": job_id,
        "flow_id": "flow-1",
        "flow_version_id": "version-1",
        "session_id": "session-1",
        "node_id": "node-1",
        "sequence_number": "2",
        "wait_timeout_seconds": 0,
        "retry_interval_seconds": 0.05,
        "lock_ttl_seconds": 120,
    }


def _lock_value_kwargs(job_id: str, token: str = "token") -> dict:
    kwargs = _lock_kwargs(job_id, token=token)
    for key in ("lock_key", "wait_timeout_seconds", "retry_interval_seconds", "lock_ttl_seconds"):
        kwargs.pop(key)
    return kwargs


def test_send_lock_value_contains_diagnostic_identifiers() -> None:
    value = send_worker._send_lock_value(**_lock_value_kwargs("job-1"))

    decoded = json.loads(value)

    assert decoded["token"] == "token"
    assert decoded["job_id"] == "job-1"
    assert decoded["tenant_id"] == "tenant-1"
    assert decoded["phone"] == "5511999999999"
    assert decoded["conversation_id"] == "conversation-1"
    assert decoded["flow_id"] == "flow-1"
    assert decoded["session_id"] == "session-1"
    assert decoded["node_id"] == "node-1"
    assert decoded["sequence_number"] == "2"


def test_release_only_deletes_lock_owned_by_current_job() -> None:
    redis = FakeRedis()
    lock_key = "wa:send-lock:tenant-1:5511999999999"
    redis.set(lock_key, send_worker._send_lock_value(**_lock_value_kwargs("job-1", token="owner-token")), ex=120, nx=True)

    send_worker._release_send_lock(redis, lock_key, "other-token", tenant_id="tenant-1", phone="5511999999999", job_id="job-2")
    assert redis.get(lock_key) is not None

    send_worker._release_send_lock(redis, lock_key, "owner-token", tenant_id="tenant-1", phone="5511999999999", job_id="job-1")
    assert redis.get(lock_key) is None


def test_second_flow_job_waits_until_previous_lock_is_released(monkeypatch) -> None:
    redis = FakeRedis()
    first_kwargs = _lock_kwargs("job-a", token="token-a")
    assert send_worker._acquire_send_lock(redis, **first_kwargs) is True

    def release_previous_lock(_seconds: float) -> None:
        send_worker._release_send_lock(redis, first_kwargs["lock_key"], "token-a", tenant_id="tenant-1", phone="5511999999999", job_id="job-a")

    monkeypatch.setattr(send_worker.time, "sleep", release_previous_lock)

    second_kwargs = _lock_kwargs("job-b", token="token-b")
    second_kwargs["wait_timeout_seconds"] = 1
    assert send_worker._acquire_send_lock(redis, **second_kwargs) is True

    decoded = json.loads(redis.get(first_kwargs["lock_key"]) or "{}")
    assert decoded["job_id"] == "job-b"
    assert decoded["token"] == "token-b"
