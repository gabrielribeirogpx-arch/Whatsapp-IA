from __future__ import annotations

import threading
import time
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.flow_v2.contracts import FlowV2EventType, FlowV2SessionStatus, RuntimeInput, RuntimeOutput
from app.flow_v2.dead_letter import FlowV2DeadLetterQueue
from app.flow_v2.delay_worker import FlowV2DelayWorker
from app.flow_v2.executor import FlowV2Executor
from app.flow_v2.metrics import FlowV2MetricsAggregator
from app.flow_v2.session_lock import FlowV2SessionLock, FlowV2SessionLockError
from app.flow_v2.snapshot import FlowV2Snapshot, canonical_hash, migrate_snapshot


class _FakeDB:
    def __init__(self):
        self.added = []

    def add(self, item):
        self.added.append(item)

    def flush(self):
        pass


class _FakeSession:
    def __init__(self, tenant_id, flow_version_id, current_node_id="start"):
        self.id = uuid.uuid4()
        self.tenant_id = tenant_id
        self.flow_version_id = flow_version_id
        self.contact_id = None
        self.conversation_id = None
        self.external_user_id = "whatsapp:+5511999999999"
        self.current_node_id = current_node_id
        self.status = FlowV2SessionStatus.RUNNING
        self.last_event_index = 0
        self.started_at = datetime.now(UTC).replace(tzinfo=None)
        self.updated_at = self.started_at


class _FakeSnapshotRepository:
    def __init__(self, snapshot):
        self.snapshot = snapshot

    def load(self, db, *, tenant_id, flow_version_id):
        return self.snapshot


class _FakeEventStore:
    def __init__(self):
        self.events = []

    def append(self, db, *, session, event_type, payload=None, node_id=None, input_message_id=None, event_version=1):
        session.last_event_index += 1
        self.events.append(
            {
                "event_index": session.last_event_index,
                "event_type": str(event_type),
                "payload": payload or {},
                "node_id": node_id,
                "input_message_id": input_message_id,
                "event_version": event_version,
            }
        )


class _FakeSessionManager:
    def __init__(self, session, event_store):
        self.session = session
        self.event_store = event_store

    def get_or_create(self, db, *, runtime_input, snapshot):
        if self.session.last_event_index == 0:
            self.event_store.append(db, session=self.session, event_type=FlowV2EventType.SESSION_STARTED)
        return self.session

    def move_to(self, db, *, session, node_id, status):
        session.current_node_id = node_id
        session.status = str(status)
        session.updated_at = datetime.now(UTC).replace(tzinfo=None)


def _snapshot():
    raw = {
        "schema_version": 1,
        "snapshot_schema_version": 1,
        "start_node_id": "start",
        "nodes": [{"id": "start", "type": "message", "content": "Olá"}, {"id": "end", "type": "message"}],
        "edges": [{"id": "e1", "source": "start", "target": "end"}],
    }
    tenant_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    return FlowV2Snapshot(
        flow_version_id=flow_version_id,
        tenant_id=tenant_id,
        hash=canonical_hash(raw),
        nodes=tuple(raw["nodes"]),
        edges=tuple(raw["edges"]),
        start_node_id=raw["start_node_id"],
        snapshot_schema_version=1,
    )


def _executor():
    snap = _snapshot()
    store = _FakeEventStore()
    session = _FakeSession(snap.tenant_id, snap.flow_version_id)
    executor = FlowV2Executor(
        snapshot_repository=_FakeSnapshotRepository(snap),
        event_store=store,
        session_manager=_FakeSessionManager(session, store),
    )
    return executor, snap, store, session, _FakeDB()


def _input(snapshot, *, input_message_id="message-1", metadata=None):
    return RuntimeInput(
        tenant_id=snapshot.tenant_id,
        flow_version_id=snapshot.flow_version_id,
        external_user_id="whatsapp:+5511999999999",
        message_text="oi",
        input_message_id=input_message_id,
        metadata=metadata or {},
    )


def test_duplicate_webhook_is_processed_once() -> None:
    executor, snapshot, store, _, db = _executor()

    first = executor.handle_input(db, _input(snapshot, input_message_id="wamid-1", metadata={"webhook_id": "webhook-1"}))
    second = executor.handle_input(db, _input(snapshot, input_message_id="wamid-1", metadata={"webhook_id": "webhook-1"}))

    assert first.emitted_event_count > 0
    assert second.emitted_event_count == 0
    assert [event["event_type"] for event in store.events].count(str(FlowV2EventType.INPUT_RECEIVED)) == 1
    assert all(event["event_version"] == 1 for event in store.events)


def test_duplicate_choice_is_processed_once() -> None:
    executor, snapshot, store, _, db = _executor()
    metadata = {"event_type": "choice", "event_id": "choice-event-1", "choice_id": "button-a"}

    executor.handle_input(db, _input(snapshot, input_message_id="choice-message", metadata=metadata))
    duplicate = executor.handle_input(db, _input(snapshot, input_message_id="choice-message", metadata=metadata))

    assert duplicate.emitted_event_count == 0
    assert [event["event_type"] for event in store.events].count(str(FlowV2EventType.INPUT_RECEIVED)) == 1


def test_duplicate_delay_job_is_processed_once() -> None:
    tenant_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    session = _FakeSession(tenant_id, flow_version_id, current_node_id="after_delay")
    job = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        session_id=session.id,
        resume_node_id="after_delay",
        run_at=datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1),
    )

    class _Result:
        def __init__(self, value):
            self.value = value

        def scalars(self):
            return self

        def __iter__(self):
            return iter(self.value)

        def scalar_one_or_none(self):
            return self.value

    class _DelayDB:
        def __init__(self):
            self.calls = 0
            self.deleted = 0

        def execute(self, statement):
            if "DELETE FROM flow_v2_scheduled_jobs" in str(statement):
                self.deleted += 1
                return _Result(None)
            self.calls += 1
            if self.calls == 1:
                return _Result([job, job])
            return _Result(session)

        def flush(self):
            pass

    class _RuntimeWorker:
        def __init__(self):
            self.count = 0

        def process(self, db, runtime_input):
            self.count += 1
            return SimpleNamespace(runtime_output=RuntimeOutput(session_id=session.id, status=FlowV2SessionStatus.WAITING, current_node_id="done"), actions=(), deliveries=())

    runtime_worker = _RuntimeWorker()
    result = FlowV2DelayWorker(runtime_worker=runtime_worker, event_store=_FakeEventStore()).run_due(_DelayDB())

    assert result.processed == 1
    assert runtime_worker.count == 1


def test_concurrent_session_execution_is_rejected() -> None:
    lock = FlowV2SessionLock()
    tenant_id = uuid.uuid4()
    session_id = uuid.uuid4()
    barrier = threading.Barrier(2)
    errors = []

    def holder():
        with lock.acquire(_FakeDB(), tenant_id=tenant_id, session_id=session_id):
            barrier.wait()
            time.sleep(0.05)

    thread = threading.Thread(target=holder)
    thread.start()
    barrier.wait()
    with pytest.raises(FlowV2SessionLockError):
        with lock.acquire(_FakeDB(), tenant_id=tenant_id, session_id=session_id):
            pass
    thread.join(timeout=1)
    assert errors == []


def test_dead_letter_generation_records_event_error_and_stacktrace() -> None:
    db = _FakeDB()
    tenant_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    error = RuntimeError("boom")

    result = FlowV2DeadLetterQueue().record(
        db,
        tenant_id=tenant_id,
        session_id=None,
        flow_version_id=flow_version_id,
        event={"input_message_id": "wamid-dead"},
        error=error,
    )

    assert result.error == "boom"
    assert "RuntimeError: boom" in result.stacktrace
    assert db.added[0].__tablename__ == "flow_v2_dead_letters"
    assert db.added[0].event["input_message_id"] == "wamid-dead"


def test_metrics_aggregation_and_snapshot_version_migration() -> None:
    tenant_id = uuid.uuid4()
    started = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=20)
    completed = SimpleNamespace(tenant_id=tenant_id, status=str(FlowV2SessionStatus.COMPLETED), started_at=started, updated_at=started + timedelta(seconds=10))
    failed = SimpleNamespace(tenant_id=tenant_id, status=str(FlowV2SessionStatus.FAILED), started_at=started, updated_at=started + timedelta(seconds=5))
    active = SimpleNamespace(tenant_id=tenant_id, status=str(FlowV2SessionStatus.WAITING), started_at=started, updated_at=started)
    db = SimpleNamespace(
        flow_v2_sessions=[completed, failed, active],
        flow_v2_events=[
            SimpleNamespace(tenant_id=tenant_id, event_type=str(FlowV2EventType.CHOICE_SHOWN)),
            SimpleNamespace(tenant_id=tenant_id, event_type=str(FlowV2EventType.CHOICE_SELECTED)),
            SimpleNamespace(tenant_id=tenant_id, event_type=str(FlowV2EventType.CHOICE_SHOWN)),
        ],
    )

    metrics = FlowV2MetricsAggregator().snapshot(db, tenant_id=tenant_id)

    assert metrics.sessions_started == 3
    assert metrics.sessions_completed == 1
    assert metrics.sessions_failed == 1
    assert metrics.average_duration == 10
    assert metrics.choice_conversion == 0.5
    assert metrics.active_sessions == 1
    assert migrate_snapshot({"schema_version": 1})["snapshot_schema_version"] == 1
