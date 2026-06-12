from __future__ import annotations

import uuid
from contextlib import contextmanager
from types import SimpleNamespace
from datetime import UTC, datetime, timedelta

import pytest

from app.flow_v2.actions import SendChoiceButtonsAction
from app.flow_v2.node_executors import calculate_typing_delay_seconds
from app.services.conversation_mode_service import set_conversation_mode
from app.flow_v2.contracts import FlowV2EventType, FlowV2SessionStatus, RuntimeInput
from app.flow_v2.delay_worker import FlowV2DelayWorker
from app.flow_v2.executor import FlowV2Executor
from app.flow_v2.snapshot import FlowV2Snapshot, canonical_hash
from app.flow_v2.transition_resolver import FlowV2TransitionError


class _FakeDB:
    def __init__(self):
        self.added = []
        self.session = None
        self.deleted = []
        self.conversation = None
        self.contact = None

    def get(self, model, item_id):
        if self.contact is not None and item_id == getattr(self.contact, "id", None):
            return self.contact
        if self.conversation is not None and item_id == getattr(self.conversation, "id", None):
            return self.conversation
        return None

    def add(self, item):
        self.added.append(item)

    def execute(self, statement, params=None):
        statement_text = str(statement)
        if "pg_try_advisory_xact_lock" in statement_text:
            return _FakeResult(scalar_value=True)
        if "DELETE FROM flow_v2_scheduled_jobs" in statement_text:
            self.deleted.append(statement)
            return _FakeResult()
        if "flow_v2_scheduled_jobs" in statement_text:
            jobs = [item for item in self.added if item.__class__.__name__ == "FlowV2ScheduledJob"]
            return _FakeResult(values=jobs)
        if "flow_v2_sessions" in statement_text:
            return _FakeResult(scalar_one_value=self.session)
        if "flow_v2_idempotency_keys" in statement_text:
            return _FakeResult(scalar_one_value=None)
        return _FakeResult()

    def flush(self):
        pass


class _FakeResult:
    def __init__(self, values=None, scalar_one_value=None, scalar_value=None):
        self.values = values or []
        self.scalar_one_value = scalar_one_value
        self.scalar_value = scalar_value

    def scalars(self):
        return self

    def __iter__(self):
        return iter(self.values)

    def scalar_one_or_none(self):
        return self.scalar_one_value

    def scalar(self):
        return self.scalar_value

    def first(self):
        return self.values[0] if self.values else None


class _FakeSession:
    def __init__(self, tenant_id, flow_version_id):
        self.id = uuid.uuid4()
        self.tenant_id = tenant_id
        self.flow_version_id = flow_version_id
        self.current_node_id = "start"
        self.external_user_id = "whatsapp:+5511999999999"
        self.contact_id = None
        self.conversation_id = None
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


class _FakeSessionLock:
    @contextmanager
    def acquire(self, db, *, tenant_id, session_id):
        yield


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
    db = _FakeDB()
    db.session = session
    return (
        FlowV2Executor(
            snapshot_repository=_FakeSnapshotRepository(snapshot),
            event_store=event_store,
            session_manager=_FakeSessionManager(session, event_store),
            session_lock=_FakeSessionLock(),
        ),
        snapshot,
        event_store,
        session,
        db,
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



def _input_with_id(snapshot, input_message_id, metadata=None):
    return RuntimeInput(
        tenant_id=snapshot.tenant_id,
        flow_version_id=snapshot.flow_version_id,
        external_user_id="whatsapp:+5511999999999",
        message_text="oi",
        input_message_id=input_message_id,
        metadata=metadata or {},
    )


def _input_with_text(snapshot, input_message_id, message_text, metadata=None):
    return RuntimeInput(
        tenant_id=snapshot.tenant_id,
        flow_version_id=snapshot.flow_version_id,
        external_user_id="whatsapp:+5511999999999",
        message_text=message_text,
        input_message_id=input_message_id,
        metadata=metadata or {},
    )


def _event_types(event_store):
    return [event["event_type"] for event in event_store.events]


def test_calculate_typing_delay_seconds_short_text_returns_minimum() -> None:
    assert calculate_typing_delay_seconds("oi") == 1.2


def test_calculate_typing_delay_seconds_medium_text_is_proportional() -> None:
    assert calculate_typing_delay_seconds("x" * 36) == 2.0


def test_calculate_typing_delay_seconds_long_text_returns_maximum() -> None:
    assert calculate_typing_delay_seconds("x" * 180) == 5.0


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

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert output.current_node_id is None
    assert output.effects == (
        {"type": "send_message", "text": "Olá mundo"},
        {"type": "send_message", "text": "Próxima"},
    )
    assert _event_types(event_store) == [
        "session.started",
        "input.received",
        "NODE_ENTERED",
        "MESSAGE_SENT",
        "NODE_EXECUTED",
        "NODE_COMPLETED",
        "TRANSITION_SELECTED",
        "NODE_ENTERED",
        "MESSAGE_SENT",
        "NODE_EXECUTED",
        "NODE_COMPLETED",
        "session.completed",
    ]
    assert event_store.events[3]["payload"] == {"node_id": "start", "message": "Olá mundo"}
    assert event_store.events[8]["payload"] == {"node_id": "next", "message": "Próxima"}


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

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert output.current_node_id is None


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

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert output.current_node_id is None
    assert "CHOICE_SHOWN" in _event_types(event_store)
    assert "CHOICE_SELECTED" in _event_types(event_store)
    assert "MESSAGE_SENT" in _event_types(event_store)
    assert event_store.events[4]["payload"] == {"node_id": "start", "row_id": row_id}
    assert any(event["payload"] == {"node_id": expected, "message": expected.upper()} for event in event_store.events)



def test_message_initial_then_choice_emits_real_interactive_buttons_action() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "data": {"isStart": True, "text": "Olá"}},
            {
                "id": "choice",
                "type": "choice",
                "data": {
                    "content": "Escolha",
                    "options": [
                        {"id": "quero_planos", "label": "Quero planos"},
                        {"id": "humano", "label": "Humano"},
                    ],
                },
            },
            {"id": "end", "type": "message", "data": {"text": "Fim"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "choice"},
            {"id": "e2", "source": "choice", "sourceHandle": "quero_planos", "target": "end"},
            {"id": "e3", "source": "choice", "sourceHandle": "humano", "target": "end"},
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    initial = executor.handle_input(db, _input_with_id(snapshot, "wamid.initial", {"provider_id": "provider-1"}))

    assert initial.status == FlowV2SessionStatus.WAITING
    assert initial.current_node_id == "choice"
    assert session.status == FlowV2SessionStatus.WAITING
    assert session.current_node_id == "choice"
    assert len(initial.actions) == 2
    assert initial.effects == ({"type": "send_message", "text": "Olá"},)
    action = initial.actions[1]
    assert isinstance(action, SendChoiceButtonsAction)
    assert action.text == "Escolha"
    assert action.node_id == "choice"
    assert list(action.buttons) == [
        {"id": "quero_planos", "title": "Quero planos"},
        {"id": "humano", "title": "Humano"},
    ]
    assert action.as_effect()["interactive"] == {
        "type": "button",
        "body": {"text": "Escolha"},
        "action": {
            "buttons": [
                {"id": "quero_planos", "title": "Quero planos"},
                {"id": "humano", "title": "Humano"},
            ]
        },
    }
    assert "CHOICE_SHOWN" in _event_types(event_store)


def test_waiting_choice_with_row_id_transitions_to_target_node() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "data": {"isStart": True, "text": "Olá"}},
            {
                "id": "choice",
                "type": "choice",
                "data": {
                    "content": "Escolha",
                    "options": [
                        {"id": "quero_planos", "label": "Quero planos"},
                        {"id": "humano", "label": "Humano"},
                    ],
                },
            },
            {"id": "plans", "type": "message", "data": {"text": "Planos"}},
            {"id": "human", "type": "message", "data": {"text": "Humano"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "choice"},
            {"id": "e2", "source": "choice", "sourceHandle": "quero_planos", "target": "plans"},
            {"id": "e3", "source": "choice", "sourceHandle": "humano", "target": "human"},
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    initial = executor.handle_input(db, _input_with_id(snapshot, "wamid.initial"))
    assert initial.status == FlowV2SessionStatus.WAITING
    assert initial.current_node_id == "choice"
    assert len(initial.actions) == 2

    selected = executor.handle_input(db, _input_with_id(snapshot, "wamid.reply", {"row_id": "quero_planos"}))

    assert selected.status == FlowV2SessionStatus.COMPLETED
    assert selected.current_node_id is None
    assert selected.effects == ({"type": "send_message", "text": "Planos"},)
    assert session.status == FlowV2SessionStatus.COMPLETED
    assert session.current_node_id is None
    assert "CHOICE_SELECTED" in _event_types(event_store)
    assert any(event["payload"] == {"node_id": "choice", "row_id": "quero_planos"} for event in event_store.events)


def test_waiting_choice_with_button_reply_id_maps_row_id_and_transitions_to_target_node() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "data": {"isStart": True, "text": "Olá"}},
            {
                "id": "choice",
                "type": "choice",
                "data": {
                    "content": "Escolha",
                    "options": [
                        {"id": "quero_planos", "label": "Quero planos"},
                        {"id": "falar_com_humano", "label": "Falar com humano"},
                    ],
                },
            },
            {"id": "plans", "type": "message", "data": {"text": "Planos"}},
            {"id": "human", "type": "message", "data": {"text": "Humano"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "choice"},
            {"id": "e2", "source": "choice", "sourceHandle": "quero_planos", "target": "plans"},
            {"id": "e3", "source": "choice", "sourceHandle": "falar_com_humano", "target": "human"},
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    initial = executor.handle_input(db, _input_with_id(snapshot, "wamid.initial"))
    assert initial.status == FlowV2SessionStatus.WAITING
    assert initial.current_node_id == "choice"

    selected = executor.handle_input(
        db,
        _input_with_id(
            snapshot,
            "wamid.button_reply",
            {"interactive_type": "button_reply", "interactive_reply_id": "quero_planos"},
        ),
    )

    input_received = next(
        event
        for event in event_store.events
        if event["event_type"] == "input.received" and event["input_message_id"] == "wamid.button_reply"
    )
    assert input_received["payload"]["metadata"]["row_id"] == "quero_planos"
    assert input_received["payload"]["metadata"]["sourceHandle"] == "quero_planos"
    assert selected.status == FlowV2SessionStatus.COMPLETED
    assert selected.current_node_id is None
    assert selected.effects == ({"type": "send_message", "text": "Planos"},)
    assert session.status == FlowV2SessionStatus.COMPLETED
    assert session.current_node_id is None
    assert len(selected.actions) == 1
    assert not any(isinstance(action, SendChoiceButtonsAction) for action in selected.actions)
    assert any(event["payload"] == {"node_id": "choice", "row_id": "quero_planos"} for event in event_store.events)

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

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert output.current_node_id is None
    condition_event = next(event for event in event_store.events if event["event_type"] == "CONDITION_EVALUATED")
    assert condition_event["payload"]["result"] is (tag == "vip")
    assert any(event["node_id"] == expected and event["event_type"] == "MESSAGE_SENT" for event in event_store.events)


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


def test_message_final_without_outgoing_edge_completes() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [{"id": "start", "type": "message", "content": "Olá"}],
        "edges": [],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    output = executor.handle_input(db, _input(snapshot))

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert output.current_node_id is None
    assert output.effects == ({"type": "send_message", "text": "Olá"},)
    assert "TRANSITION_NOT_FOUND" not in _event_types(event_store)
    assert _event_types(event_store)[-1] == "session.completed"
    assert session.status == FlowV2SessionStatus.COMPLETED


def test_message_to_condition_waits_before_evaluating_condition() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Menu inicial"},
            {"id": "check", "type": "condition", "data": {"keywords": ["1"]}},
            {"id": "final", "type": "message", "content": "okk1"},
            {"id": "fallback", "type": "message", "content": "Opção inválida"},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "check"},
            {"id": "e2", "source": "check", "sourceHandle": "true", "target": "final"},
            {"id": "e3", "source": "check", "sourceHandle": "false", "target": "fallback"},
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    output = executor.handle_input(db, _input_with_text(snapshot, "wamid.menu.initial", "Oi"))

    assert output.status == FlowV2SessionStatus.WAITING
    assert output.current_node_id == "check"
    assert session.status == FlowV2SessionStatus.WAITING
    assert session.current_node_id == "check"
    assert output.effects == ({"type": "send_message", "text": "Menu inicial"},)
    assert [event["node_id"] for event in event_store.events if event["event_type"] == "NODE_ENTERED"] == ["start"]
    assert "CONDITION_EVALUATED" not in _event_types(event_store)
    assert "session.waiting" in _event_types(event_store)


def test_waiting_message_to_condition_resumes_with_next_user_message() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Menu inicial"},
            {"id": "check", "type": "condition", "data": {"keywords": ["1"]}},
            {"id": "final", "type": "message", "content": "okk1"},
            {"id": "fallback", "type": "message", "content": "Opção inválida"},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "check"},
            {"id": "e2", "source": "check", "sourceHandle": "true", "target": "final"},
            {"id": "e3", "source": "check", "sourceHandle": "false", "target": "fallback"},
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    initial = executor.handle_input(db, _input_with_text(snapshot, "wamid.menu.initial", "Oi"))
    assert initial.status == FlowV2SessionStatus.WAITING
    assert initial.current_node_id == "check"

    resumed = executor.handle_input(db, _input_with_text(snapshot, "wamid.menu.reply", "1"))

    assert resumed.status == FlowV2SessionStatus.COMPLETED
    assert resumed.current_node_id is None
    assert session.status == FlowV2SessionStatus.COMPLETED
    assert resumed.effects == ({"type": "send_message", "text": "okk1"},)
    assert [event["node_id"] for event in event_store.events if event["event_type"] == "NODE_ENTERED"] == ["start", "check", "final"]
    condition_event = next(event for event in event_store.events if event["event_type"] == "CONDITION_EVALUATED")
    assert condition_event["payload"]["message"] == "1"
    assert condition_event["payload"]["result"] is True
    assert [event["payload"]["target_node_id"] for event in event_store.events if event["event_type"] == "TRANSITION_SELECTED"] == ["final"]


def test_start_message_to_message_chain_continues_automatically() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Início", "data": {"isStart": True}},
            {"id": "middle", "type": "message", "content": "Meio"},
            {"id": "end", "type": "message", "content": "Fim"},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "middle"},
            {"id": "e2", "source": "middle", "target": "end"},
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    output = executor.handle_input(db, _input(snapshot))

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert output.current_node_id is None
    assert session.status == FlowV2SessionStatus.COMPLETED
    assert output.effects == (
        {"type": "send_message", "text": "Início"},
        {"type": "send_message", "text": "Meio"},
        {"type": "send_message", "text": "Fim"},
    )
    assert [event["node_id"] for event in event_store.events if event["event_type"] == "NODE_ENTERED"] == ["start", "middle", "end"]
    assert "session.waiting" not in _event_types(event_store)


def test_start_message_to_delay_schedules_without_waiting_before_delay_and_resumes_next_message() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Início", "data": {"isStart": True}},
            {"id": "delay", "type": "delay", "seconds": 5},
            {"id": "after_delay", "type": "message", "content": "Depois"},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "delay"},
            {"id": "e2", "source": "delay", "target": "after_delay"},
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    initial = executor.handle_input(db, _input_with_id(snapshot, "wamid.delay.initial"))

    assert initial.status == FlowV2SessionStatus.WAITING
    assert initial.current_node_id == "after_delay"
    assert session.status == FlowV2SessionStatus.WAITING
    assert initial.effects == ({"type": "send_message", "text": "Início"},)
    assert [event["node_id"] for event in event_store.events if event["event_type"] == "NODE_ENTERED"] == ["start", "delay"]
    assert "DELAY_SCHEDULED" in _event_types(event_store)
    scheduled_jobs = [item for item in db.added if item.__class__.__name__ == "FlowV2ScheduledJob"]
    assert len(scheduled_jobs) == 1
    assert scheduled_jobs[0].resume_node_id == "after_delay"
    assert initial.actions[-1].as_effect()["type"] == "schedule_delay"
    assert initial.actions[-1].as_effect()["seconds"] == 5

    resumed = executor.handle_input(db, _input_with_id(snapshot, "wamid.delay.resume"))

    assert resumed.status == FlowV2SessionStatus.COMPLETED
    assert resumed.current_node_id is None
    assert session.status == FlowV2SessionStatus.COMPLETED
    assert resumed.effects == ({"type": "send_message", "text": "Depois"},)
    assert [event["node_id"] for event in event_store.events if event["event_type"] == "NODE_ENTERED"] == ["start", "delay", "after_delay"]


def test_delay_worker_resume_dispatches_message_delay_message_default_pipeline() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Olá! Como posso te ajudar?", "data": {"isStart": True}},
            {"id": "delay", "type": "delay", "seconds": 5},
            {"id": "bccab03d-830a-4dc1-9e67-bcadf5666eee", "type": "message", "content": "Certo, vou encaminhar para esses planos."},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "delay"},
            {"id": "e2", "source": "delay", "target": "bccab03d-830a-4dc1-9e67-bcadf5666eee"},
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)
    initial = executor.handle_input(db, _input_with_id(snapshot, "wamid.delay.initial"))
    scheduled_job = next(item for item in db.added if item.__class__.__name__ == "FlowV2ScheduledJob")
    scheduled_job.run_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=1)

    delay_worker = FlowV2DelayWorker(event_store=event_store)
    delay_worker.runtime_worker.executor = executor
    assert delay_worker.runtime_worker.channel_adapter is not None
    sent_payloads = []
    delay_worker.runtime_worker.channel_adapter.client = lambda **kwargs: sent_payloads.append(kwargs) or {"status": "queued"}

    result = delay_worker.run_due(db, now=datetime.now(UTC).replace(tzinfo=None))

    assert initial.effects == ({"type": "send_message", "text": "Olá! Como posso te ajudar?"},)
    assert result.processed == 1
    assert result.worker_results[0].runtime_output.status == FlowV2SessionStatus.COMPLETED
    assert result.worker_results[0].runtime_output.current_node_id is None
    assert result.worker_results[0].runtime_output.effects == ({"type": "send_message", "text": "Certo, vou encaminhar para esses planos."},)
    assert [action.text for action in result.worker_results[0].runtime_output.actions if hasattr(action, "text")] == ["Certo, vou encaminhar para esses planos."]
    assert [action.text for action in result.worker_results[0].actions if hasattr(action, "text")] == ["Certo, vou encaminhar para esses planos."]
    assert result.worker_results[0].deliveries == ({"status": "queued"},)
    assert sent_payloads[0]["text"] == "Certo, vou encaminhar para esses planos."
    assert sent_payloads[0]["recipient_id"] == "whatsapp:+5511999999999"
    assert [event["node_id"] for event in event_store.events if event["event_type"] == "NODE_ENTERED"] == [
        "start",
        "delay",
        "bccab03d-830a-4dc1-9e67-bcadf5666eee",
    ]


def test_start_message_to_condition_waits_before_condition_branch() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Olá! Como posso te ajudar?", "data": {"isStart": True}},
            {"id": "check", "type": "condition", "conditions": [{"field": "contact.tag", "operator": "==", "value": "vip"}]},
            {"id": "answer_a", "type": "message", "content": "Resposta A"},
            {"id": "answer_b", "type": "message", "content": "Resposta B"},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "check"},
            {"id": "e2", "source": "check", "sourceHandle": "true", "target": "answer_a"},
            {"id": "e3", "source": "check", "sourceHandle": "false", "target": "answer_b"},
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    output = executor.handle_input(db, _input(snapshot, {"contact": {"tag": "vip"}}))

    assert output.status == FlowV2SessionStatus.WAITING
    assert output.current_node_id == "check"
    assert session.status == FlowV2SessionStatus.WAITING
    assert session.current_node_id == "check"
    assert output.effects == ({"type": "send_message", "text": "Olá! Como posso te ajudar?"},)
    assert [event["node_id"] for event in event_store.events if event["event_type"] == "NODE_ENTERED"] == ["start"]
    assert "CONDITION_EVALUATED" not in _event_types(event_store)
    assert "session.waiting" in _event_types(event_store)


def test_start_message_to_action_to_message_executes_automatically() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Início", "data": {"isStart": True}},
            {"id": "action", "type": "action"},
            {"id": "end", "type": "message", "content": "Depois da ação"},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "action"},
            {"id": "e2", "source": "action", "target": "end"},
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    output = executor.handle_input(db, _input(snapshot))

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert output.current_node_id is None
    assert session.status == FlowV2SessionStatus.COMPLETED
    assert output.effects == (
        {"type": "send_message", "text": "Início"},
        {"type": "send_message", "text": "Depois da ação"},
    )
    assert [event["node_id"] for event in event_store.events if event["event_type"] == "NODE_ENTERED"] == ["start", "action", "end"]
    assert "session.waiting" not in _event_types(event_store)

def test_loop_protection_fails_after_max_steps() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "condition", "conditions": [{"field": "loop", "operator": "==", "value": True}]},
            {"id": "again", "type": "condition", "conditions": [{"field": "loop", "operator": "==", "value": True}]},
        ],
        "edges": [
            {"id": "e1", "source": "start", "sourceHandle": "true", "target": "again"},
            {"id": "e2", "source": "again", "sourceHandle": "true", "target": "start"},
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    with pytest.raises(RuntimeError, match="max_steps=50"):
        executor.handle_input(db, _input(snapshot, {"loop": True}))

    assert [event["event_type"] for event in event_store.events].count("NODE_ENTERED") == 50
    assert event_store.events[-1]["event_type"] == "session.failed"
    assert event_store.events[-1]["payload"] == {"reason": "max_steps_exceeded", "max_steps": 50}
    assert session.status == FlowV2SessionStatus.FAILED

@pytest.mark.parametrize(
    ("display_mode", "expected_interactive_type", "reply_metadata"),
    [
        ("buttons", "button", {"interactive_reply_id": "next", "interactive_type": "button_reply"}),
        ("list", "list", {"interactive_reply_id": "next", "interactive_type": "list_reply"}),
    ],
)
def test_message_choice_display_mode_sends_clicks_transitions_and_completes(display_mode, expected_interactive_type, reply_metadata) -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "data": {"isStart": True, "text": "Olá"}},
            {
                "id": "choice",
                "type": "choice",
                "data": {
                    "content": "Escolha",
                    "display_mode": display_mode,
                    "options": [{"id": "next", "label": "Continuar"}],
                },
            },
            {"id": "end", "type": "message", "data": {"text": "Fim"}},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "choice"},
            {"id": "e2", "source": "choice", "sourceHandle": "next", "target": "end"},
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    initial = executor.handle_input(db, _input_with_id(snapshot, f"wamid.{display_mode}.initial"))

    assert initial.status == FlowV2SessionStatus.WAITING
    assert initial.current_node_id == "choice"
    assert len(initial.actions) == 2
    action = initial.actions[1]
    assert isinstance(action, SendChoiceButtonsAction)
    assert action.display_mode == display_mode
    assert action.metadata["interactive_type"] == expected_interactive_type
    assert action.as_effect()["interactive"]["type"] == expected_interactive_type
    if display_mode == "buttons":
        assert action.as_effect()["interactive"]["action"]["buttons"] == [{"id": "next", "title": "Continuar"}]
    else:
        assert action.as_effect()["interactive"]["action"]["sections"] == [
            {"title": "Opções", "rows": [{"id": "next", "title": "Continuar"}]}
        ]

    selected = executor.handle_input(db, _input_with_id(snapshot, f"wamid.{display_mode}.reply", reply_metadata))

    assert selected.status == FlowV2SessionStatus.COMPLETED
    assert selected.current_node_id is None
    assert selected.effects == ({"type": "send_message", "text": "Fim"},)
    assert session.status == FlowV2SessionStatus.COMPLETED
    assert session.current_node_id is None
    assert any(event["payload"] == {"node_id": "choice", "row_id": "next"} for event in event_store.events)
    assert not any(isinstance(action, SendChoiceButtonsAction) for action in selected.actions)


@pytest.mark.parametrize("action_type", ["create_lead", "add_tag", "notify_team", "transfer_human"])
def test_message_to_action_to_message_continues_runtime_v2(action_type) -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Antes"},
            {
                "id": "action",
                "type": "action",
                "data": {
                    "action_type": action_type,
                    "params": {
                        "tag": "vip",
                        "message": "Atender lead",
                        "reason": "solicitou humano",
                        "lead_name": "Lead Teste",
                    },
                },
            },
            {"id": "end", "type": "message", "content": "Depois"},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "action"},
            {"id": "e2", "source": "action", "target": "end"},
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    output = executor.handle_input(db, _input(snapshot))

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert output.current_node_id is None
    assert output.effects == (
        {"type": "send_message", "text": "Antes"},
        {"type": "send_message", "text": "Depois"},
    )
    assert session.status == FlowV2SessionStatus.COMPLETED
    assert session.current_node_id is None
    assert any(
        event["event_type"] == "NODE_EXECUTED"
        and event["node_id"] == "action"
        and event["payload"] == {"node_type": "action", "status": "continue"}
        for event in event_store.events
    )


def test_transfer_human_marks_conversation_and_blocks_next_runtime_execution() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Mensagem"},
            {
                "id": "action",
                "type": "action",
                "data": {
                    "action_type": "transfer_human",
                    "params": {"reason": "solicitou humano"},
                },
            },
            {"id": "end", "type": "message", "content": "Humano acionado"},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "action"},
            {"id": "e2", "source": "action", "target": "end"},
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)
    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=snapshot.tenant_id,
        phone_number="+5511999999999",
        mode="flow",
        context={},
    )
    db.conversation = conversation

    first = executor.handle_input(db, RuntimeInput(
        tenant_id=snapshot.tenant_id,
        flow_version_id=snapshot.flow_version_id,
        external_user_id="whatsapp:+5511999999999",
        message_text="oi",
        conversation_id=conversation.id,
        input_message_id="wamid.transfer.first",
        metadata={},
    ))

    assert first.status == FlowV2SessionStatus.COMPLETED
    assert first.effects == (
        {"type": "send_message", "text": "Mensagem"},
        {"type": "send_message", "text": "Humano acionado"},
    )
    assert conversation.mode == "human"
    assert conversation.context["transfer_reason"] == "solicitou humano"
    assert any(
        event["event_type"] == "NODE_EXECUTED"
        and event["node_id"] == "action"
        and event["payload"] == {"node_type": "action", "status": "continue"}
        for event in event_store.events
    )

    emitted_after_first = len(event_store.events)
    second = executor.handle_input(db, RuntimeInput(
        tenant_id=snapshot.tenant_id,
        flow_version_id=snapshot.flow_version_id,
        external_user_id="whatsapp:+5511999999999",
        message_text="oi de novo",
        conversation_id=conversation.id,
        input_message_id="wamid.transfer.second",
        metadata={},
    ))

    assert second.status == FlowV2SessionStatus.COMPLETED
    assert second.actions == ()
    assert second.effects == ()
    assert second.emitted_event_count == 0
    assert len(event_store.events) == emitted_after_first


@pytest.mark.parametrize("mode", ["human", "bot", "ai"])
def test_set_conversation_mode_action_updates_mode_and_continues_runtime_v2(mode) -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Antes"},
            {"id": "action", "type": "action", "data": {"action_type": "set_conversation_mode", "mode": mode}},
            {"id": "end", "type": "message", "content": "Depois"},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "action"},
            {"id": "e2", "source": "action", "target": "end"},
        ],
    }
    executor, snapshot, _, _, db = _executor(raw_snapshot)
    conversation = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=snapshot.tenant_id, contact_id=None, phone_number="+5511999999999",
        name="Cliente", avatar_url=None, assigned_user_id=uuid.uuid4(), assigned_user_name="Agente",
        mode="flow", context={}, updated_at=None,
    )
    db.conversation = conversation

    output = executor.handle_input(db, RuntimeInput(
        tenant_id=snapshot.tenant_id,
        flow_version_id=snapshot.flow_version_id,
        external_user_id="whatsapp:+5511999999999",
        message_text="oi",
        conversation_id=conversation.id,
        input_message_id=f"wamid.mode.{mode}",
        metadata={},
    ))

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert output.effects == ({"type": "send_message", "text": "Antes"}, {"type": "send_message", "text": "Depois"})
    assert conversation.mode == mode
    if mode == "bot":
        assert conversation.assigned_user_id is None
        assert conversation.assigned_user_name is None
    assert any(item.__class__.__name__ == "AuditLog" for item in db.added)


def test_set_conversation_mode_terminal_action_completes_runtime_v2() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "action",
        "nodes": [{"id": "action", "type": "action", "data": {"action_type": "set_conversation_mode", "mode": "bot"}}],
        "edges": [],
    }
    executor, snapshot, _, session, db = _executor(raw_snapshot)
    conversation = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=snapshot.tenant_id, contact_id=None, phone_number="+5511999999999",
        name="Cliente", avatar_url=None, assigned_user_id=None, assigned_user_name=None, mode="flow", context={}, updated_at=None,
    )
    db.conversation = conversation

    output = executor.handle_input(db, RuntimeInput(
        tenant_id=snapshot.tenant_id,
        flow_version_id=snapshot.flow_version_id,
        external_user_id="whatsapp:+5511999999999",
        message_text="oi",
        conversation_id=conversation.id,
        input_message_id="wamid.mode.terminal",
        metadata={},
    ))

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert output.effects == ()
    assert session.status == FlowV2SessionStatus.COMPLETED
    assert conversation.mode == "bot"


def test_set_conversation_mode_realtime_and_audit_are_dispatched(monkeypatch) -> None:
    db = _FakeDB()
    tenant_id = uuid.uuid4()
    conversation = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=tenant_id, contact_id=None, phone_number="+5511999999999",
        name="Cliente", avatar_url=None, assigned_user_id=None, assigned_user_name=None, mode="ai", updated_at=None,
    )
    published = []
    monkeypatch.setattr("app.services.conversation_mode_service.sync_publish", lambda channel, payload: published.append((channel, payload)))

    set_conversation_mode(db, tenant_id=tenant_id, conversation=conversation, mode="human", flow_execution_id="flow-exec-1")

    assert conversation.mode == "human"
    assert any(item.__class__.__name__ == "AuditLog" and item.action == "CONVERSATION_MODE_CHANGED" for item in db.added)
    assert any(channel == f"dashboard:{tenant_id}" and payload["event"] == "conversation_updated" for channel, payload in published)
    assert any(channel == f"{tenant_id}:{conversation.id}" for channel, _ in published)


def test_set_conversation_mode_enforces_tenant_isolation() -> None:
    db = _FakeDB()
    conversation = SimpleNamespace(id=uuid.uuid4(), tenant_id=uuid.uuid4(), phone_number="+5511999999999", mode="bot")

    with pytest.raises(ValueError, match="tenant"):
        set_conversation_mode(db, tenant_id=uuid.uuid4(), conversation=conversation, mode="human")


def test_set_conversation_mode_invalid_mode_fails_controlled_runtime_v2() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "action",
        "nodes": [{"id": "action", "type": "action", "data": {"action_type": "set_conversation_mode", "mode": "invalid"}}],
        "edges": [],
    }
    executor, snapshot, _, session, db = _executor(raw_snapshot)
    db.conversation = SimpleNamespace(
        id=uuid.uuid4(), tenant_id=snapshot.tenant_id, contact_id=None, phone_number="+5511999999999",
        name="Cliente", avatar_url=None, assigned_user_id=None, assigned_user_name=None, mode="flow", context={}, updated_at=None,
    )

    with pytest.raises(RuntimeError, match="Invalid conversation mode"):
        executor.handle_input(db, RuntimeInput(
            tenant_id=snapshot.tenant_id,
            flow_version_id=snapshot.flow_version_id,
            external_user_id="whatsapp:+5511999999999",
            message_text="oi",
            conversation_id=db.conversation.id,
            input_message_id="wamid.mode.invalid",
            metadata={},
        ))
    assert session.status == FlowV2SessionStatus.FAILED


def test_delay_with_show_typing_sends_indicator_and_schedules_job(monkeypatch) -> None:
    calls = []

    def fake_typing(db, **kwargs):
        calls.append(kwargs)
        return {"status": "sent"}

    monkeypatch.setattr(
        "app.services.whatsapp_message_service.send_whatsapp_typing_indicator_safe",
        fake_typing,
    )
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "delay", "seconds": 3, "data": {"show_typing": True}},
            {"id": "next", "type": "message", "content": "Depois"},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "next"}],
    }
    executor, snapshot, _, session, db = _executor(raw_snapshot)
    runtime_input = RuntimeInput(
        tenant_id=snapshot.tenant_id,
        flow_version_id=snapshot.flow_version_id,
        external_user_id="whatsapp:+5511999999999",
        message_id="wamid.example",
        metadata={"provider_id": "provider-1"},
    )

    output = executor.handle_input(db, runtime_input)

    scheduled_jobs = [item for item in db.added if item.__class__.__name__ == "FlowV2ScheduledJob"]
    assert output.status == FlowV2SessionStatus.WAITING
    assert len(scheduled_jobs) == 1
    assert scheduled_jobs[0].resume_node_id == "next"
    assert len(calls) == 1
    assert calls[0]["tenant_id"] == session.tenant_id
    assert calls[0]["message_id"] == "wamid.example"
    assert calls[0]["recipient_id"] == "whatsapp:+5511999999999"
    assert calls[0]["context"]["node_id"] == "start"


def test_delay_typing_failure_still_returns_scheduled(monkeypatch) -> None:
    def fake_typing(db, **kwargs):
        raise RuntimeError("meta down")

    monkeypatch.setattr(
        "app.services.whatsapp_message_service.send_whatsapp_typing_indicator_safe",
        fake_typing,
    )
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "delay", "seconds": 3, "data": {"show_typing": True}},
            {"id": "next", "type": "message", "content": "Depois"},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "next"}],
    }
    executor, snapshot, _, session, db = _executor(raw_snapshot)
    output = executor.handle_input(db, _input(snapshot, {"message_id": "wamid.example"}))

    scheduled_jobs = [item for item in db.added if item.__class__.__name__ == "FlowV2ScheduledJob"]
    assert output.status == FlowV2SessionStatus.WAITING
    assert session.status == FlowV2SessionStatus.WAITING
    assert len(scheduled_jobs) == 1
    assert scheduled_jobs[0].resume_node_id == "next"


def test_delay_show_typing_false_does_not_send_indicator(monkeypatch) -> None:
    def fake_typing(db, **kwargs):
        raise AssertionError("typing indicator should not be sent")

    monkeypatch.setattr(
        "app.services.whatsapp_message_service.send_whatsapp_typing_indicator_safe",
        fake_typing,
    )
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "delay", "seconds": 3, "data": {"show_typing": False}},
            {"id": "next", "type": "message", "content": "Depois"},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "next"}],
    }
    executor, snapshot, _, _, db = _executor(raw_snapshot)

    output = executor.handle_input(db, _input(snapshot))

    scheduled_jobs = [item for item in db.added if item.__class__.__name__ == "FlowV2ScheduledJob"]
    assert output.status == FlowV2SessionStatus.WAITING
    assert len(scheduled_jobs) == 1


def test_delay_show_typing_missing_mode_keeps_configured_delay(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.whatsapp_message_service.send_whatsapp_typing_indicator_safe",
        lambda db, **kwargs: {"status": "sent"},
    )
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "delay", "seconds": 3, "data": {"show_typing": True}},
            {"id": "next", "type": "message", "content": "x" * 90},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "next"}],
    }
    executor, snapshot, event_store, _, db = _executor(raw_snapshot)

    output = executor.handle_input(db, _input(snapshot))

    delay_event = next(event for event in event_store.events if event["event_type"] == "DELAY_SCHEDULED")
    assert output.actions[0].seconds == 3
    assert delay_event["payload"]["seconds"] == 3
    assert delay_event["payload"]["typing_duration_mode"] == "delay"


def test_delay_show_typing_delay_mode_keeps_configured_delay(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.whatsapp_message_service.send_whatsapp_typing_indicator_safe",
        lambda db, **kwargs: {"status": "sent"},
    )
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "delay", "seconds": 4, "data": {"show_typing": True, "typing_duration_mode": "delay"}},
            {"id": "next", "type": "message", "content": "x" * 90},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "next"}],
    }
    executor, snapshot, event_store, _, db = _executor(raw_snapshot)

    output = executor.handle_input(db, _input(snapshot))

    delay_event = next(event for event in event_store.events if event["event_type"] == "DELAY_SCHEDULED")
    assert output.actions[0].seconds == 4
    assert delay_event["payload"]["seconds"] == 4


def test_delay_show_typing_auto_mode_uses_next_message_length(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.whatsapp_message_service.send_whatsapp_typing_indicator_safe",
        lambda db, **kwargs: {"status": "sent"},
    )
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "delay", "seconds": 10, "data": {"show_typing": True, "typing_duration_mode": "auto"}},
            {"id": "next", "type": "message", "data": {"text": "x" * 36}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "next"}],
    }
    executor, snapshot, event_store, _, db = _executor(raw_snapshot)

    output = executor.handle_input(db, _input(snapshot))

    delay_event = next(event for event in event_store.events if event["event_type"] == "DELAY_SCHEDULED")
    assert output.actions[0].seconds == 2.0
    assert delay_event["payload"]["seconds"] == 2.0
    assert delay_event["payload"]["configured_seconds"] == 10
    assert delay_event["payload"]["typing_duration_mode"] == "auto"


def test_delay_auto_mode_next_non_message_falls_back_to_configured_delay(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.whatsapp_message_service.send_whatsapp_typing_indicator_safe",
        lambda db, **kwargs: {"status": "sent"},
    )
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "delay", "seconds": 7, "data": {"show_typing": True, "typing_duration_mode": "auto"}},
            {"id": "next", "type": "condition", "data": {"condition": "sim"}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "next"}],
    }
    executor, snapshot, event_store, _, db = _executor(raw_snapshot)

    output = executor.handle_input(db, _input(snapshot))

    delay_event = next(event for event in event_store.events if event["event_type"] == "DELAY_SCHEDULED")
    assert output.actions[0].seconds == 7
    assert delay_event["payload"]["seconds"] == 7


def test_delay_auto_mode_calculation_error_falls_back_to_configured_delay(monkeypatch) -> None:
    monkeypatch.setattr(
        "app.services.whatsapp_message_service.send_whatsapp_typing_indicator_safe",
        lambda db, **kwargs: {"status": "sent"},
    )

    def fail_calculation(text: str) -> float:
        raise RuntimeError("bad template")

    monkeypatch.setattr("app.flow_v2.node_executors.calculate_typing_delay_seconds", fail_calculation)
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "delay", "seconds": 6, "data": {"show_typing": True, "typing_duration_mode": "auto"}},
            {"id": "next", "type": "message", "content": "Depois"},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "next"}],
    }
    executor, snapshot, event_store, _, db = _executor(raw_snapshot)

    output = executor.handle_input(db, _input(snapshot))

    delay_event = next(event for event in event_store.events if event["event_type"] == "DELAY_SCHEDULED")
    assert output.actions[0].seconds == 6
    assert delay_event["payload"]["seconds"] == 6


def _input_for_contact(snapshot, *, contact_id, conversation_id=None, tenant_id=None):
    return RuntimeInput(
        tenant_id=tenant_id or snapshot.tenant_id,
        flow_version_id=snapshot.flow_version_id,
        external_user_id="whatsapp:+5511999999999",
        message_text="oi",
        contact_id=contact_id,
        conversation_id=conversation_id,
        input_message_id=f"wamid.{uuid.uuid4()}",
    )


def test_terminal_action_returns_complete_without_next_node() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Antes"},
            {"id": "action", "type": "action", "data": {"action_type": "notify_team", "params": {"message": "Fim"}}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "action"}],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    output = executor.handle_input(db, _input(snapshot))

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert output.current_node_id is None
    assert session.status == FlowV2SessionStatus.COMPLETED
    assert session.current_node_id is None
    assert any(
        event["event_type"] == "NODE_EXECUTED"
        and event["node_id"] == "action"
        and event["payload"] == {"node_type": "action", "status": "complete"}
        for event in event_store.events
    )


def test_add_tag_action_adds_tag_and_runtime_continues_to_next_node(monkeypatch) -> None:
    from app.services import contact_tag_service

    published = []
    monkeypatch.setattr(contact_tag_service, "sync_publish", lambda channel, payload: published.append((channel, payload)))
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "action",
        "nodes": [
            {"id": "action", "type": "action", "data": {"action_type": "add_tag", "params": {"tag": "financeiro"}}},
            {"id": "end", "type": "message", "content": "Tag aplicada com sucesso"},
        ],
        "edges": [{"id": "e1", "source": "action", "target": "end"}],
    }
    executor, snapshot, _event_store, _session, db = _executor(raw_snapshot)
    contact = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=snapshot.tenant_id,
        phone="+5511999999999",
        name="Cliente",
        avatar_url=None,
        tags_json=[],
        score=0,
        lifecycle_stage=None,
        last_interaction_at=None,
        updated_at=None,
    )
    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=snapshot.tenant_id,
        contact_id=contact.id,
        phone_number=contact.phone,
    )
    db.contact = contact
    db.conversation = conversation

    output = executor.handle_input(db, _input_for_contact(snapshot, contact_id=contact.id, conversation_id=conversation.id))

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert output.effects == ({"type": "send_message", "text": "Tag aplicada com sucesso"},)
    assert contact.tags_json == ["financeiro"]
    assert contact.updated_at is not None
    assert any(getattr(event, "type", None) == "tag_added" for event in db.added)
    assert any(channel == f"dashboard:{snapshot.tenant_id}" for channel, _payload in published)
    assert any(channel == f"{snapshot.tenant_id}:{conversation.id}" for channel, _payload in published)


def test_add_tag_action_does_not_duplicate_existing_tag(monkeypatch) -> None:
    from app.services import contact_tag_service

    published = []
    monkeypatch.setattr(contact_tag_service, "sync_publish", lambda channel, payload: published.append((channel, payload)))
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "action",
        "nodes": [{"id": "action", "type": "action", "data": {"action_type": "add_tag", "params": {"tag": "financeiro"}}}],
        "edges": [],
    }
    executor, snapshot, _event_store, _session, db = _executor(raw_snapshot)
    contact = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=snapshot.tenant_id,
        phone="+5511999999999",
        tags_json=["financeiro"],
        last_interaction_at=None,
        updated_at=None,
    )
    db.contact = contact

    output = executor.handle_input(db, _input_for_contact(snapshot, contact_id=contact.id))

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert contact.tags_json == ["financeiro"]
    assert not any(getattr(event, "type", None) == "tag_added" for event in db.added)
    assert published == []


def test_add_tag_action_respects_tenant_isolation() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "action",
        "nodes": [{"id": "action", "type": "action", "data": {"action_type": "add_tag", "params": {"tag": "financeiro"}}}],
        "edges": [],
    }
    executor, snapshot, _event_store, _session, db = _executor(raw_snapshot)
    other_tenant_id = uuid.uuid4()
    contact = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=other_tenant_id,
        phone="+5511999999999",
        tags_json=[],
        last_interaction_at=None,
        updated_at=None,
    )
    db.contact = contact

    output = executor.handle_input(db, _input_for_contact(snapshot, contact_id=contact.id))

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert contact.tags_json == []
    assert db.added == []


def test_create_lead_action_passes_runtime_context_and_continues(monkeypatch) -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "action",
        "nodes": [
            {
                "id": "action",
                "type": "action",
                "data": {"action_type": "create_lead", "params": {"lead_name": "Gabriel Teste"}},
            },
            {"id": "end", "type": "message", "content": "Lead criado com sucesso"},
        ],
        "edges": [{"id": "e1", "source": "action", "target": "end"}],
    }
    executor, snapshot, _event_store, session, db = _executor(raw_snapshot)
    contact_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    calls = []

    def fake_create_or_update(db_arg, **kwargs):
        calls.append({"db": db_arg, **kwargs})

    monkeypatch.setattr("app.flow_v2.node_executors.create_or_update_lead_from_flow_action", fake_create_or_update)

    output = executor.handle_input(
        db,
        RuntimeInput(
            tenant_id=snapshot.tenant_id,
            flow_version_id=snapshot.flow_version_id,
            external_user_id="whatsapp:+5511999999999",
            message_text="oi",
            contact_id=contact_id,
            conversation_id=conversation_id,
            input_message_id="wamid.create-lead.context",
            metadata={"contact_name": "Nome Metadata"},
        ),
    )

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert output.effects == ({"type": "send_message", "text": "Lead criado com sucesso"},)
    assert calls == [
        {
            "db": db,
            "tenant_id": session.tenant_id,
            "phone": "+5511999999999",
            "contact_id": contact_id,
            "conversation_id": conversation_id,
            "lead_name": "Gabriel Teste",
            "last_message": "oi",
            "metadata": {"contact_name": "Nome Metadata"},
        }
    ]


def test_create_lead_terminal_action_completes_when_service_fails(monkeypatch) -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "action",
        "nodes": [
            {
                "id": "action",
                "type": "action",
                "data": {"action_type": "create_lead", "params": {"lead_name": "Lead"}},
            },
        ],
        "edges": [],
    }
    executor, snapshot, _event_store, session, db = _executor(raw_snapshot)

    def raise_controlled_error(*_args, **_kwargs):
        raise RuntimeError("crm temporarily unavailable")

    monkeypatch.setattr("app.flow_v2.node_executors.create_or_update_lead_from_flow_action", raise_controlled_error)

    output = executor.handle_input(db, _input_with_id(snapshot, "wamid.create-lead.terminal"))

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert output.effects == ()
    assert session.status == FlowV2SessionStatus.COMPLETED
    assert session.current_node_id is None
