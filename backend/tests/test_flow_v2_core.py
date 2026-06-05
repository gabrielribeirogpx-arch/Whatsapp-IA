from __future__ import annotations

import uuid

import pytest

from app.flow_v2.contracts import FlowV2EventType, FlowV2SessionStatus, RuntimeInput
from app.flow_v2.executor import FlowV2Executor
from app.flow_v2.snapshot import FlowV2Snapshot, canonical_hash
from app.flow_v2.transition_resolver import FlowV2TransitionError


class _FakeDB:
    def __init__(self):
        self.added = []

    def add(self, item):
        self.added.append(item)

    def flush(self):
        pass


class _FakeSession:
    def __init__(self, tenant_id, flow_version_id):
        self.id = uuid.uuid4()
        self.tenant_id = tenant_id
        self.flow_version_id = flow_version_id
        self.current_node_id = "start"
        self.status = FlowV2SessionStatus.RUNNING
        self.last_event_index = 0


class _FakeSnapshotRepository:
    def __init__(self, snapshot):
        self.snapshot = snapshot
        self.loaded_with = None

    def load(self, db, *, tenant_id, flow_version_id):
        self.loaded_with = {"tenant_id": tenant_id, "flow_version_id": flow_version_id}
        return self.snapshot


class _FakeEventStore:
    def __init__(self):
        self.events = []

    def append(self, db, *, session, event_type, payload=None, node_id=None, input_message_id=None):
        session.last_event_index += 1
        self.events.append(
            {
                "event_index": session.last_event_index,
                "event_type": str(event_type),
                "payload": payload or {},
                "node_id": node_id,
                "input_message_id": input_message_id,
            }
        )


class _FakeSessionManager:
    def __init__(self, session, event_store):
        self.session = session
        self.event_store = event_store

    def get_or_create(self, db, *, runtime_input, snapshot):
        if self.session.last_event_index == 0:
            self.event_store.append(
                db,
                session=self.session,
                event_type=FlowV2EventType.SESSION_STARTED,
                payload={"snapshot_hash": snapshot.hash, "start_node_id": snapshot.start_node_id},
            )
        return self.session

    def move_to(self, db, *, session, node_id, status):
        session.current_node_id = node_id
        session.status = str(status)


def _snapshot(raw_snapshot, tenant_id=None, flow_version_id=None):
    tenant_id = tenant_id or uuid.uuid4()
    flow_version_id = flow_version_id or uuid.uuid4()
    return FlowV2Snapshot(
        flow_version_id=flow_version_id,
        tenant_id=tenant_id,
        hash=canonical_hash(raw_snapshot),
        nodes=tuple(raw_snapshot["nodes"]),
        edges=tuple(raw_snapshot["edges"]),
        start_node_id=raw_snapshot["start_node_id"],
    )


def _executor(raw_snapshot):
    snapshot = _snapshot(raw_snapshot)
    event_store = _FakeEventStore()
    session = _FakeSession(snapshot.tenant_id, snapshot.flow_version_id)
    return (
        FlowV2Executor(
            snapshot_repository=_FakeSnapshotRepository(snapshot),
            event_store=event_store,
            session_manager=_FakeSessionManager(session, event_store),
        ),
        snapshot,
        event_store,
        session,
        _FakeDB(),
    )


def _input(snapshot, metadata=None):
    return RuntimeInput(
        tenant_id=snapshot.tenant_id,
        flow_version_id=snapshot.flow_version_id,
        external_user_id="whatsapp:+5511999999999",
        message_text="oi",
        input_message_id="wamid.1",
        metadata=metadata or {},
    )


def _event_types(event_store):
    return [event["event_type"] for event in event_store.events]


def test_canonical_hash_ignores_embedded_hash_key() -> None:
    snapshot = {"schema_version": 1, "start_node_id": "start", "nodes": [], "edges": []}
    with_hash = {**snapshot, "hash": "client-side-copy"}

    assert canonical_hash(snapshot) == canonical_hash({k: v for k, v in with_hash.items() if k != "hash"})


def test_message_to_message_navigates_to_next_node_and_emits_events() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Olá mundo"},
            {"id": "next", "type": "message", "content": "Próxima"},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "next"}],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    output = executor.handle_input(db, _input(snapshot))

    assert output.status == FlowV2SessionStatus.WAITING
    assert output.current_node_id == "next"
    assert output.effects == ({"type": "send_message", "text": "Olá mundo"},)
    assert _event_types(event_store) == [
        "session.started",
        "input.received",
        "NODE_ENTERED",
        "MESSAGE_SENT",
        "NODE_EXECUTED",
        "NODE_COMPLETED",
        "TRANSITION_SELECTED",
        "session.waiting",
    ]
    assert event_store.events[3]["payload"] == {"node_id": "start", "message": "Olá mundo"}


def test_default_source_handle_edge_navigates_linear_node() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Olá mundo"},
            {"id": "next", "type": "message", "content": "Próxima"},
        ],
        "edges": [{"id": "e1", "source": "start", "sourceHandle": "default", "target": "next"}],
    }
    executor, snapshot, _event_store, _session, db = _executor(raw_snapshot)

    output = executor.handle_input(db, _input(snapshot))

    assert output.status == FlowV2SessionStatus.WAITING
    assert output.current_node_id == "next"


@pytest.mark.parametrize(("row_id", "expected"), [("op_a", "a"), ("op_b", "b")])
def test_choice_navigates_by_option_id_only(row_id, expected) -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {
                "id": "start",
                "type": "choice",
                "options": [{"id": "op_a", "label": "Opção A"}, {"id": "op_b", "label": "Opção B"}],
            },
            {"id": "a", "type": "message", "content": "A"},
            {"id": "b", "type": "message", "content": "B"},
        ],
        "edges": [
            {"id": "e1", "source": "start", "sourceHandle": "op_a", "target": "a"},
            {"id": "e2", "source": "start", "sourceHandle": "op_b", "target": "b"},
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    output = executor.handle_input(db, _input(snapshot, {"row_id": row_id}))

    assert output.current_node_id == expected
    assert "CHOICE_SHOWN" in _event_types(event_store)
    assert "CHOICE_SELECTED" in _event_types(event_store)
    assert event_store.events[4]["payload"] == {"node_id": "start", "row_id": row_id}


def test_delay_scheduling_creates_scheduled_job_and_does_not_execute_next_node() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [{"id": "start", "type": "delay", "seconds": 3600}, {"id": "next", "type": "message", "content": "Depois"}],
        "edges": [{"id": "e1", "source": "start", "target": "next"}],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    output = executor.handle_input(db, _input(snapshot))

    assert output.effects == ()
    assert output.status == FlowV2SessionStatus.WAITING
    assert output.current_node_id == "next"
    scheduled_jobs = [item for item in db.added if item.__class__.__name__ == "FlowV2ScheduledJob"]
    assert len(scheduled_jobs) == 1
    assert scheduled_jobs[0].session_id == session.id
    assert scheduled_jobs[0].resume_node_id == "next"
    assert "DELAY_SCHEDULED" in _event_types(event_store)


@pytest.mark.parametrize(("tag", "expected"), [("vip", "vip_node"), ("regular", "normal_node")])
def test_condition_evaluates_simple_equality(tag, expected) -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "condition", "conditions": [{"field": "contact.tag", "operator": "==", "value": "vip"}]},
            {"id": "vip_node", "type": "message", "content": "VIP"},
            {"id": "normal_node", "type": "message", "content": "Normal"},
        ],
        "edges": [
            {"id": "e1", "source": "start", "sourceHandle": "true", "target": "vip_node"},
            {"id": "e2", "source": "start", "sourceHandle": "false", "target": "normal_node"},
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    output = executor.handle_input(db, _input(snapshot, {"contact": {"tag": tag}}))

    assert output.current_node_id == expected
    condition_event = next(event for event in event_store.events if event["event_type"] == "CONDITION_EVALUATED")
    assert condition_event["payload"]["result"] is (tag == "vip")


def test_ambiguous_transition_emits_event_and_aborts_execution() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [{"id": "start", "type": "message", "content": "Olá"}, {"id": "a", "type": "message"}, {"id": "b", "type": "message"}],
        "edges": [
            {"id": "e1", "source": "start", "target": "a"},
            {"id": "e2", "source": "start", "target": "b"},
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    with pytest.raises(FlowV2TransitionError):
        executor.handle_input(db, _input(snapshot))

    assert "TRANSITION_AMBIGUOUS" in _event_types(event_store)
    assert session.status == FlowV2SessionStatus.FAILED


def test_missing_transition_emits_event_and_aborts_execution() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [{"id": "start", "type": "message", "content": "Olá"}],
        "edges": [],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    with pytest.raises(FlowV2TransitionError):
        executor.handle_input(db, _input(snapshot))

    assert "TRANSITION_NOT_FOUND" in _event_types(event_store)
    assert session.status == FlowV2SessionStatus.FAILED
