from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace


os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import worker as delay_worker_module


class _FakeRedis:
    async def zrangebyscore(self, *args, **kwargs):
        return []

    async def zrem(self, *args, **kwargs):
        return 0

    async def zadd(self, *args, **kwargs):
        return 1


class _FakeDB:
    def __init__(self):
        self.committed = False
        self.rolled_back = False

    def commit(self):
        self.committed = True

    def rollback(self):
        self.rolled_back = True

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _FakeSessionLocal:
    def __init__(self):
        self.db = _FakeDB()

    def __call__(self):
        return self.db


class _FakeFlowV2DelayWorker:
    def __init__(self):
        self.calls = []

    def run_due(self, db, *, now=None, limit=100):
        self.calls.append({"db": db, "now": now, "limit": limit})
        return SimpleNamespace(processed=2)


def test_delay_worker_polls_flow_v2_scheduled_jobs_before_legacy_redis(monkeypatch) -> None:
    session_local = _FakeSessionLocal()
    flow_v2_delay_worker = _FakeFlowV2DelayWorker()
    monkeypatch.setattr(delay_worker_module, "SessionLocal", session_local)

    worker = delay_worker_module.DelayWorker(
        redis_url="redis://example.invalid/0",
        flow_v2_delay_worker=flow_v2_delay_worker,
    )
    worker.redis = _FakeRedis()

    asyncio.run(worker._process_due_jobs_once())

    assert len(flow_v2_delay_worker.calls) == 1
    assert flow_v2_delay_worker.calls[0]["db"] is session_local.db
    assert session_local.db.committed is True
    assert session_local.db.rolled_back is False
