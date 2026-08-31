from __future__ import annotations

import uuid
import logging
from contextlib import contextmanager
from types import SimpleNamespace
from datetime import UTC, datetime, timedelta

import pytest

from app.flow_v2.actions import SendChoiceButtonsAction, SendCtaUrlAction, SendMessageAction
from app.flow_v2.node_executors import calculate_typing_delay_seconds
from app.services.conversation_mode_service import set_conversation_mode
from app.flow_v2.contracts import FlowV2EventType, FlowV2SessionStatus, RuntimeInput
from app.flow_v2.delay_worker import FlowV2DelayWorker
from app.flow_v2.executor import FlowV2Executor
from app.flow_v2.snapshot import FlowV2Snapshot, canonical_hash
from app.flow_v2.transition_resolver import FlowV2TransitionError
from app.flow_v2.executors.base_executor import NodeExecutionResult


class _FakeDB:
    def __init__(self):
        self.added = []
        self.session = None
        self.deleted = []
        self.conversation = None
        self.contact = None
        self.lead = None

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
        if "leads" in statement_text:
            return _FakeResult(values=[self.lead] if self.lead is not None else [])
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

    def all(self):
        if self.values:
            return self.values
        return [self.scalar_one_value] if self.scalar_one_value is not None else []

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
        self.context = {}
        self.variables = {}


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


@pytest.mark.parametrize("items", [[], [{"id": "slot1", "label": "09:00"}], [
    {"id": "slot1", "label": "09:00", "description": "Dr. João", "icon": "📅"},
    {"id": "slot2", "label": "11:00", "description": "Dr. João"},
]])
def test_dynamic_choice_materializes_mcp_array_and_saves_selection(items) -> None:
    raw_snapshot = {
        "schema_version": 1, "start_node_id": "choice",
        "nodes": [
            {"id": "choice", "type": "choice", "data": {"isStart": True, "content": "Horários", "options_mode": "dynamic", "options_variable": "appointments", "label_field": "label", "value_field": "id", "description_field": "description", "icon_field": "icon", "result_variable": "selected_slot"}},
            {"id": "end", "type": "message", "data": {"text": "{{selected_slot}} {{selected_slot_title}} {{selected_slot_object.label}}"}},
        ],
        "edges": [{"id": "next", "source": "choice", "sourceHandle": "default", "target": "end"}],
    }
    executor, snapshot, _events, session, db = _executor(raw_snapshot)
    session.current_node_id = "choice"
    # This is the same canonical variables store populated by MCPToolNodeExecutor.
    session.variables["appointments"] = items
    initial = executor.handle_input(db, _input_with_id(snapshot, f"initial-{len(items)}"))
    action = initial.actions[-1]
    assert isinstance(action, SendChoiceButtonsAction)
    assert len(action.options) == len(items)
    if not items:
        return
    selected = executor.handle_input(db, _input_with_id(snapshot, f"selected-{len(items)}", {"interactive_type": "list_reply", "interactive_reply_id": items[-1]["id"]}))
    assert session.variables["selected_slot"] == items[-1]["id"]
    assert session.variables["selected_slot_title"] == items[-1]["label"]
    assert session.variables["selected_slot_index"] == len(items) - 1
    assert session.variables["selected_slot_object"] == items[-1]
    assert items[-1]["id"] in selected.actions[-1].text
    assert items[-1]["label"] in selected.actions[-1].text


def test_dynamic_choice_empty_uses_canonical_message() -> None:
    raw_snapshot = {
        "schema_version": 1, "start_node_id": "choice",
        "nodes": [{"id": "choice", "type": "choice_dynamic", "data": {"isStart": True, "options_mode": "dynamic", "options_variable": "appointments", "label_field": "label", "value_field": "id", "empty_message": "Sem horários para {{period}}."}}],
        "edges": [],
    }
    executor, snapshot, _events, session, db = _executor(raw_snapshot)
    session.current_node_id = "choice"
    session.variables.update({"appointments": [], "period": "amanhã"})
    result = executor.handle_input(db, _input_with_id(snapshot, "empty-message"))
    assert result.actions[0].text == "Sem horários para amanhã."


def test_dynamic_choice_empty_routes_canonical_handle() -> None:
    raw_snapshot = {
        "schema_version": 1, "start_node_id": "choice",
        "nodes": [
            {"id": "choice", "type": "choice_dynamic", "data": {"isStart": True, "options_mode": "dynamic", "options_variable": "appointments", "label_field": "label", "value_field": "id"}},
            {"id": "fallback", "type": "message", "data": {"content": "Escolha outro período", "is_terminal": True}},
        ],
        "edges": [{"id": "empty", "source": "choice", "sourceHandle": "empty", "target": "fallback"}],
    }
    executor, snapshot, _events, session, db = _executor(raw_snapshot)
    session.current_node_id = "choice"
    session.variables["appointments"] = []
    result = executor.handle_input(db, _input_with_id(snapshot, "empty-edge"))
    assert result.actions[0].text == "Escolha outro período"


@pytest.mark.parametrize("intent_category", ["Aparelho", "Limpeza", "Implante"])
@pytest.mark.parametrize(
    "placeholder", ["{{intent_category}}", "{{variables.intent_category}}"]
)
def test_choice_renders_canonical_session_variables_in_interactive_payload(
    intent_category, placeholder, caplog
) -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "choice",
        "nodes": [
            {
                "id": "choice",
                "type": "choice",
                "content": f"Tratamento: {placeholder}",
                "header": "Categoria: {{variables.intent_category}}",
                "footer": "Selecionado: {intent_category}",
                "options": [
                    {"id": "continuar", "label": "Continuar"},
                    {"id": "voltar", "label": "Voltar"},
                ],
            }
        ],
        "edges": [],
    }
    executor, snapshot, _event_store, session, db = _executor(raw_snapshot)
    session.variables = {"intent_category": intent_category}
    session.current_node_id = "choice"

    with caplog.at_level(logging.INFO):
        output = executor.handle_input(db, _input(snapshot))

    action = output.actions[0]
    assert isinstance(action, SendChoiceButtonsAction)
    assert action.text == f"Tratamento: {intent_category}"
    assert action.as_effect()["interactive"]["body"]["text"] == action.text
    assert list(action.buttons) == [
        {"id": "continuar", "title": "Continuar"},
        {"id": "voltar", "title": "Voltar"},
    ]
    assert action.metadata["header"] == f"Categoria: {intent_category}"
    assert action.metadata["footer"] == f"Selecionado: {intent_category}"
    assert "event=RUNTIME_V2_CHOICE_RENDER" in caplog.text
    assert "missing_keys=[]" in caplog.text


@pytest.mark.parametrize(
    ("missing_behavior", "expected"),
    [("empty", "Tratamento: "), ("preserve", "Tratamento: {{missing}}")],
)
def test_choice_honors_missing_variable_behavior(
    missing_behavior, expected, monkeypatch, caplog
) -> None:
    monkeypatch.setenv("FLOW_V2_MISSING_VARIABLE", missing_behavior)
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "choice",
        "nodes": [
            {
                "id": "choice",
                "type": "choice",
                "body_text": "Tratamento: {{missing}}",
                "options": [{"id": "ok", "label": "OK"}],
            }
        ],
        "edges": [],
    }
    executor, snapshot, _event_store, session, db = _executor(raw_snapshot)
    session.current_node_id = "choice"

    with caplog.at_level(logging.WARNING):
        output = executor.handle_input(db, _input(snapshot))

    assert output.actions[0].text == expected
    assert "missing_keys=['missing']" in caplog.text


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


def test_terminal_flagged_data_collection_waits_then_consumes_success_transition(caplog) -> None:
    """Regression: a stale terminal flag must not finish a collection checkpoint."""
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "appointment-date",
        "nodes": [
            {
                "id": "appointment-date",
                "type": "data_collection",
                "is_terminal": True,
                "data": {"variable_name": "appointment_date", "data_type": "text"},
            },
            {"id": "ask-name", "type": "message", "data": {"text": "Qual o nome da pessoa?"}},
        ],
        "edges": [
            {
                "id": "appointment-success",
                "source": "appointment-date",
                "sourceHandle": "success",
                "target": "ask-name",
            }
        ],
    }
    executor, snapshot, _event_store, session, db = _executor(raw_snapshot)
    session.current_node_id = "appointment-date"

    with caplog.at_level(logging.INFO):
        waiting = executor.handle_input(db, _input_with_id(snapshot, "wamid.choice"))
        resumed = executor.handle_input(
            db,
            _input_with_text(snapshot, "wamid.appointment", "Segunda-feira às 11:00"),
        )

    assert waiting.status == FlowV2SessionStatus.WAITING
    assert waiting.current_node_id == "appointment-date"
    assert session.variables["appointment_date"] == "Segunda-feira às 11:00"
    assert resumed.status == FlowV2SessionStatus.COMPLETED
    assert resumed.effects == ({"type": "send_message", "text": "Qual o nome da pessoa?"},)
    assert "event=RUNTIME_V2_DATA_COLLECTION_RECEIVED" in caplog.text
    assert "event=RUNTIME_V2_DATA_COLLECTION_SAVE" in caplog.text
    assert "event=RUNTIME_V2_DATA_COLLECTION_RESULT" in caplog.text
    assert "event=RUNTIME_V2_DATA_COLLECTION_TRANSITION" in caplog.text
    assert "event=RUNTIME_V2_DATA_COLLECTION_ENQUEUE" in caplog.text
    assert "event=RUNTIME_V2_DATA_COLLECTION_MESSAGE_EXECUTION" in caplog.text
    assert "transition_id=appointment-success source_handle=success next_node_id=ask-name" in caplog.text


@pytest.mark.parametrize("middle_type", ["message", "condition", "action", None])
def test_choice_reply_is_consumed_before_a_later_choice(middle_type) -> None:
    """A reply to Choice #1 must never be reused as the reply to Choice #2."""
    nodes = [
        {
            "id": "choice-1",
            "type": "choice",
            "data": {
                "content": "Primeira escolha",
                "options": [{"id": "yes", "label": "Sim"}],
            },
        },
        {
            "id": "choice-2",
            "type": "choice",
            "data": {
                "content": "Segunda escolha",
                "options": [{"id": "yes", "label": "Sim"}],
            },
        },
        {"id": "done", "type": "message", "data": {"text": "Não deve ser enviada"}},
    ]
    edges = [
        {"id": "choice-2-yes", "source": "choice-2", "sourceHandle": "yes", "target": "done"},
    ]
    target_after_first = "choice-2"
    if middle_type == "message":
        nodes.append({"id": "middle", "type": "message", "data": {"text": "Entre escolhas"}})
        edges.append({"id": "middle-next", "source": "middle", "target": "choice-2"})
        target_after_first = "middle"
    elif middle_type == "condition":
        nodes.append({"id": "middle", "type": "condition", "data": {"conditions": []}})
        edges.append({"id": "middle-next", "source": "middle", "sourceHandle": "false", "target": "choice-2"})
        target_after_first = "middle"
    elif middle_type == "action":
        nodes.append({"id": "middle", "type": "action", "data": {"action_type": "test_noop"}})
        edges.append({"id": "middle-next", "source": "middle", "target": "choice-2"})
        target_after_first = "middle"
    edges.append(
        {"id": "choice-1-yes", "source": "choice-1", "sourceHandle": "yes", "target": target_after_first}
    )
    executor, snapshot, event_store, session, db = _executor(
        {
            "schema_version": 1,
            "start_node_id": "choice-1",
            "nodes": nodes,
            "edges": edges,
        }
    )
    session.current_node_id = "choice-1"

    first = executor.handle_input(db, _input_with_id(snapshot, "wamid.initial"))
    assert first.status == FlowV2SessionStatus.WAITING
    assert first.current_node_id == "choice-1"

    reply = _input_with_id(
        snapshot,
        "wamid.reply",
        {"interactive_reply_id": "yes", "selected_row_id": "yes"},
    )
    second = executor.handle_input(db, reply)

    assert second.status == FlowV2SessionStatus.WAITING
    assert second.current_node_id == "choice-2"
    assert session.status == FlowV2SessionStatus.WAITING
    assert session.current_node_id == "choice-2"
    assert isinstance(second.actions[-1], SendChoiceButtonsAction)
    assert second.actions[-1].node_id == "choice-2"
    assert all(action.as_effect().get("text") != "Não deve ser enviada" for action in second.actions)
    assert [event["node_id"] for event in event_store.events if event["event_type"] == "CHOICE_SELECTED"] == ["choice-1"]
    # The original input remains intact for audit/event payloads; only the
    # traversal copy has its already-consumed selection removed.
    assert reply.metadata["runtime_choice_key"] == "yes"


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


def test_terminal_cta_url_node_completes_and_emits_send_cta_url_action() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {
                "id": "start",
                "type": "cta_url",
                "data": {
                    "content": "Veja nossos planos",
                    "button_text": "Abrir link",
                    "url": "https://example.com/planos",
                },
            },
        ],
        "edges": [],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    output = executor.handle_input(db, _input_with_id(snapshot, "wamid.cta.terminal"))

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert output.current_node_id is None
    assert len(output.actions) == 1
    action = output.actions[0]
    assert isinstance(action, SendCtaUrlAction)
    assert action.action_type == "send_cta_url"
    assert action.metadata["node_type"] == "cta_url"
    assert action.as_effect()["interactive_type"] == "cta_url"
    assert "MESSAGE_SENT" in _event_types(event_store)


def test_non_terminal_cta_url_node_continues_to_next_node() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {
                "id": "start",
                "type": "cta_url",
                "text": "Veja nossos planos",
                "button_text": "Abrir link",
                "url": "https://example.com/planos",
            },
            {"id": "next", "type": "message", "content": "Depois do link"},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "next"}],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    output = executor.handle_input(db, _input_with_id(snapshot, "wamid.cta.next"))

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert output.current_node_id is None
    assert len(output.actions) == 2
    assert isinstance(output.actions[0], SendCtaUrlAction)
    assert output.actions[1].as_effect()["type"] == "send_message"
    assert output.actions[1].as_effect()["text"] == "Depois do link"
    assert any(event["event_type"] == "TRANSITION_SELECTED" and event["payload"] == {"target_node_id": "next"} for event in event_store.events)

def test_message_wait_for_reply_pauses_at_next_node_and_does_not_repeat_greeting() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Olá! Como posso te ajudar?", "data": {"wait_for_reply": True}},
            {"id": "rag", "type": "ai_rag", "data": {"question": "{{last_message}}", "fallback_message": "Resposta IA/RAG"}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "rag"}],
    }
    executor, snapshot, _event_store, session, db = _executor(raw_snapshot)

    initial = executor.handle_input(db, _input_with_text(snapshot, "wamid.start", "oi"))

    assert initial.status == FlowV2SessionStatus.WAITING
    assert initial.current_node_id == "rag"
    assert [action.as_effect()["text"] for action in initial.actions] == ["Olá! Como posso te ajudar?"]

    resumed = executor.handle_input(db, _input_with_text(snapshot, "wamid.rag", "me fale sobre o edital"))

    assert resumed.status == FlowV2SessionStatus.COMPLETED
    assert resumed.current_node_id is None
    assert [action.as_effect()["text"] for action in resumed.actions] == ["Resposta IA/RAG"]

    after_finished = executor.handle_input(db, _input_with_text(snapshot, "wamid.after-finished", "tenho outra pergunta"))

    assert after_finished.status == FlowV2SessionStatus.COMPLETED
    assert after_finished.current_node_id is None
    assert after_finished.actions == ()
    sent_texts = [
        event["payload"].get("message")
        for event in _event_store.events
        if event["event_type"] == str(FlowV2EventType.MESSAGE_SENT)
    ]
    assert sent_texts == ["Olá! Como posso te ajudar?", "Resposta IA/RAG"]


def test_message_wait_for_reply_primes_data_collection_and_consumes_first_reply_after_reload() -> None:
    """A Message boundary must not make the first collection reply an initializer."""
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "ask-period",
        "nodes": [
            {
                "id": "ask-period", "type": "message", "content": "Qual período prefere?",
                "data": {"wait_for_reply": True},
            },
            {
                "id": "preferred-period", "type": "data_collection",
                "data": {"variable_name": "preferred_period", "data_type": "text"},
            },
            {"id": "check-availability", "type": "mcp_tool", "data": {}},
        ],
        "edges": [
            {"id": "ask-to-collect", "source": "ask-period", "target": "preferred-period"},
            {
                "id": "collection-success", "source": "preferred-period",
                "sourceHandle": "success", "target": "check-availability",
            },
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)
    session.current_node_id = "ask-period"

    class _FakeCheckAvailability:
        def __init__(self):
            self.executions = 0

        def execute(self, db, *, snapshot, session, node, runtime_input):
            self.executions += 1
            session.variables["availability_checked"] = True
            return NodeExecutionResult(status="complete")

    fake_check = _FakeCheckAvailability()
    executor.node_registry._executors["mcp_tool"] = fake_check

    first = executor.handle_input(db, _input_with_text(snapshot, "wamid.ask", "tratamento salvo"))

    assert first.status == FlowV2SessionStatus.WAITING
    assert first.current_node_id == "preferred-period"
    assert [action.as_effect()["text"] for action in first.actions] == ["Qual período prefere?"]
    assert session.context["waiting_variable"] == "preferred_period"

    # Mimic JSON persistence/reload between separate worker deliveries.
    session.context = dict(session.context)
    session.context["data_collection"] = dict(session.context["data_collection"])
    session.context["data_collection"]["processed_message_ids"] = list(
        session.context["data_collection"]["processed_message_ids"]
    )
    session.variables = dict(session.variables)

    second = executor.handle_input(
        db,
        _input_with_text(snapshot, "wamid.period", "Tarde do dia 04/09/2026 às 14:30hrs"),
    )

    assert second.status == FlowV2SessionStatus.COMPLETED
    assert session.variables["preferred_period"] == "Tarde do dia 04/09/2026 às 14:30hrs"
    assert session.variables["availability_checked"] is True
    assert fake_check.executions == 1
    assert [action.as_effect()["text"] for action in first.actions + second.actions] == ["Qual período prefere?"]
    assert any(
        event["event_type"] == "TRANSITION_SELECTED"
        and event["node_id"] == "preferred-period"
        and event["payload"] == {"source_handle": "success", "target_node_id": "check-availability"}
        for event in event_store.events
    )


def test_terminal_marked_node_finishes_even_when_edge_exists() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Olá", "data": {"wait_for_reply": True}},
            {"id": "rag", "type": "ai_rag", "data": {"question": "{{last_message}}", "fallback_message": "Resposta IA/RAG", "endFlow": True}},
            {"id": "restart", "type": "message", "content": "Olá! Como posso te ajudar?"},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "rag"},
            {"id": "e2", "source": "rag", "target": "restart"},
        ],
    }
    executor, snapshot, event_store, _session, db = _executor(raw_snapshot)

    initial = executor.handle_input(db, _input_with_text(snapshot, "wamid.terminal.start", "oi"))
    resumed = executor.handle_input(db, _input_with_text(snapshot, "wamid.terminal.rag", "qual o prazo?"))

    assert initial.status == FlowV2SessionStatus.WAITING
    assert resumed.status == FlowV2SessionStatus.COMPLETED
    assert resumed.current_node_id is None
    assert [action.as_effect()["text"] for action in resumed.actions] == ["Resposta IA/RAG"]
    sent_texts = [
        event["payload"].get("message")
        for event in event_store.events
        if event["event_type"] == str(FlowV2EventType.MESSAGE_SENT)
    ]
    assert sent_texts == ["Olá", "Resposta IA/RAG"]


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


def test_menu_reply_two_resumes_conditions_and_routes_to_comercial() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Menu inicial: 1 Suporte, 2 Comercial"},
            {"id": "condition_1", "type": "condition", "data": {"keywords": ["1"]}},
            {"id": "condition_2", "type": "condition", "data": {"keywords": ["2"]}},
            {"id": "suporte", "type": "message", "content": "Suporte"},
            {"id": "comercial", "type": "message", "content": "Comercial"},
            {"id": "fallback", "type": "message", "content": "Opção inválida"},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "condition_1"},
            {"id": "e2", "source": "condition_1", "sourceHandle": "true", "target": "suporte"},
            {"id": "e3", "source": "condition_1", "sourceHandle": "false", "target": "condition_2"},
            {"id": "e4", "source": "condition_2", "sourceHandle": "true", "target": "comercial"},
            {"id": "e5", "source": "condition_2", "sourceHandle": "false", "target": "fallback"},
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    initial = executor.handle_input(db, _input_with_text(snapshot, "wamid.menu.initial.2", "oi"))
    resumed = executor.handle_input(db, _input_with_text(snapshot, "wamid.menu.reply.2", "2"))

    assert initial.status == FlowV2SessionStatus.WAITING
    assert initial.current_node_id == "condition_1"
    assert resumed.status == FlowV2SessionStatus.COMPLETED
    assert resumed.current_node_id is None
    assert session.status == FlowV2SessionStatus.COMPLETED
    assert resumed.effects == ({"type": "send_message", "text": "Comercial"},)
    condition_events = [event for event in event_store.events if event["event_type"] == "CONDITION_EVALUATED"]
    assert [event["node_id"] for event in condition_events] == ["condition_1", "condition_2"]
    assert [event["payload"]["message"] for event in condition_events] == ["2", "2"]
    assert [event["payload"]["result"] for event in condition_events] == [False, True]


@pytest.mark.parametrize(
    ("reply", "expected_text"),
    [
        ("1", "Financeiro"),
        ("2", "Comercial"),
        ("3", "Suporte Técnico"),
        ("4", "Humano"),
    ],
)
def test_numeric_text_resumes_waiting_condition_menu_branches(reply, expected_text, caplog) -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Menu: 1 Financeiro, 2 Comercial, 3 Suporte Técnico, 4 Humano"},
            {"id": "condition_1", "type": "condition", "data": {"keywords": ["1"]}},
            {"id": "condition_2", "type": "condition", "data": {"keywords": ["2"]}},
            {"id": "condition_3", "type": "condition", "data": {"keywords": ["3"]}},
            {"id": "condition_4", "type": "condition", "data": {"keywords": ["4"]}},
            {"id": "financeiro", "type": "message", "content": "Financeiro"},
            {"id": "comercial", "type": "message", "content": "Comercial"},
            {"id": "suporte", "type": "message", "content": "Suporte Técnico"},
            {"id": "humano", "type": "message", "content": "Humano"},
            {"id": "fallback", "type": "message", "content": "Opção inválida"},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "condition_1"},
            {"id": "e2", "source": "condition_1", "sourceHandle": "true", "target": "financeiro"},
            {"id": "e3", "source": "condition_1", "sourceHandle": "false", "target": "condition_2"},
            {"id": "e4", "source": "condition_2", "sourceHandle": "true", "target": "comercial"},
            {"id": "e5", "source": "condition_2", "sourceHandle": "false", "target": "condition_3"},
            {"id": "e6", "source": "condition_3", "sourceHandle": "true", "target": "suporte"},
            {"id": "e7", "source": "condition_3", "sourceHandle": "false", "target": "condition_4"},
            {"id": "e8", "source": "condition_4", "sourceHandle": "true", "target": "humano"},
            {"id": "e9", "source": "condition_4", "sourceHandle": "false", "target": "fallback"},
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    initial = executor.handle_input(db, _input_with_text(snapshot, f"wamid.numeric.initial.{reply}", "oi"))
    assert initial.status == FlowV2SessionStatus.WAITING
    assert initial.current_node_id == "condition_1"

    with caplog.at_level("INFO", logger="app.flow_v2.executor"):
        resumed = executor.handle_input(db, _input_with_text(snapshot, f"wamid.numeric.reply.{reply}", reply))

    assert resumed.status == FlowV2SessionStatus.COMPLETED
    assert resumed.effects == ({"type": "send_message", "text": expected_text},)
    assert session.current_node_id is None
    assert any(
        "event=runtime_numeric_choice_detected" in record.message
        and f"message_text={reply}" in record.message
        and "current_node_id=condition_1" in record.message
        for record in caplog.records
    )
    condition_events = [event for event in event_store.events if event["event_type"] == "CONDITION_EVALUATED"]
    assert all(event["payload"]["message"] == reply for event in condition_events)


def test_numeric_text_resumes_waiting_choice_without_breaking_interactive_reply() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Escolha"},
            {"id": "choice", "type": "choice", "data": {"options": [{"id": "1", "label": "Financeiro"}, {"id": "2", "label": "Comercial"}]}},
            {"id": "financeiro", "type": "message", "content": "Financeiro"},
            {"id": "comercial", "type": "message", "content": "Comercial"},
        ],
        "edges": [
            {"id": "e1", "source": "start", "target": "choice"},
            {"id": "e2", "source": "choice", "sourceHandle": "1", "target": "financeiro"},
            {"id": "e3", "source": "choice", "sourceHandle": "2", "target": "comercial"},
        ],
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    initial = executor.handle_input(db, _input_with_text(snapshot, "wamid.choice.initial.numeric", "oi"))
    assert initial.status == FlowV2SessionStatus.WAITING
    assert initial.current_node_id == "choice"

    selected = executor.handle_input(db, _input_with_text(snapshot, "wamid.choice.reply.numeric", "2"))

    assert selected.status == FlowV2SessionStatus.COMPLETED
    assert selected.effects == ({"type": "send_message", "text": "Comercial"},)
    assert any(event["payload"] == {"node_id": "choice", "row_id": "2"} for event in event_store.events)

    executor, snapshot, event_store, session, db = _executor(raw_snapshot)
    executor.handle_input(db, _input_with_text(snapshot, "wamid.choice.initial.interactive", "oi"))
    selected = executor.handle_input(
        db,
        _input_with_text(
            snapshot,
            "wamid.choice.reply.interactive",
            "texto ignorado",
            {"interactive_reply_id": "1", "interactive_type": "button_reply"},
        ),
    )

    assert selected.status == FlowV2SessionStatus.COMPLETED
    assert selected.effects == ({"type": "send_message", "text": "Financeiro"},)
    assert any(event["payload"] == {"node_id": "choice", "row_id": "1"} for event in event_store.events)


def test_message_to_condition_wait_logs_waiting_for_reply(caplog) -> None:
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
    executor, snapshot, _event_store, _session, db = _executor(raw_snapshot)

    with caplog.at_level("INFO", logger="app.flow_v2.executors._legacy"):
        executor.handle_input(db, _input_with_text(snapshot, "wamid.menu.log", "oi"))

    assert any(
        "event=message_node_waiting_for_reply" in record.message
        and "message_node_id=start" in record.message
        and "next_node_id=check" in record.message
        for record in caplog.records
    )

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
def test_message_choice_display_mode_sends_clicks_transitions_and_completes(display_mode, expected_interactive_type, reply_metadata, caplog) -> None:
    caplog.set_level(logging.INFO)
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
    trace = caplog.text
    assert "stage=session_loaded status=found" in trace
    assert "current_node_id=choice waiting_for_choice=True" in trace
    assert "stage=choice_node_lookup status=found" in trace
    assert "runtime_choice_key=next" in trace
    assert "stage=choice_option_lookup status=found" in trace
    assert "option_id=next source_handle=next" in trace
    assert "stage=transition_lookup status=found" in trace
    assert "next_node_id=end" in trace
    assert "stage=next_node_selected status=success" in trace
    assert "stage=node_entered status=success reason=executor_entered_node session_id=" in trace
    assert "node_id=end node_type=message" in trace


@pytest.mark.parametrize("action_type", ["create_lead", "add_tag", "notify_team", "transfer_human", "create_task"])
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


def _notify_team_snapshot(*, params=None, with_next=False):
    nodes = [{"id": "action", "type": "action", "data": {"action_type": "notify_team", **({"params": params} if params is not None else {})}}]
    edges = []
    if with_next:
        nodes.append({"id": "end", "type": "message", "content": "Operador avisado"})
        edges.append({"id": "e1", "source": "action", "target": "end"})
    return {"schema_version": 1, "start_node_id": "action", "nodes": nodes, "edges": edges}


def _attach_notify_conversation(db, snapshot, *, tenant_id=None):
    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id or snapshot.tenant_id,
        contact_id=uuid.uuid4(),
        phone_number="+5511999999999",
        name="Cliente Teste",
        updated_at=None,
    )
    db.conversation = conversation
    return conversation


def test_notify_team_creates_activity_audit_realtime_and_defaults_priority(monkeypatch) -> None:
    from app.flow_v2 import node_executors

    published = []
    monkeypatch.setattr(node_executors, "sync_publish", lambda channel, payload: published.append((channel, payload)))
    executor, snapshot, _event_store, session, db = _executor(
        _notify_team_snapshot(params={"notification_title": "Financeiro", "notification_message": "Cliente aguardando pagamento."})
    )
    conversation = _attach_notify_conversation(db, snapshot)

    output = executor.handle_input(db, _input_for_contact(snapshot, contact_id=conversation.contact_id, conversation_id=conversation.id))

    assert output.status == FlowV2SessionStatus.COMPLETED
    audit = next(item for item in db.added if item.__class__.__name__ == "AuditLog")
    assert audit.action == "TEAM_NOTIFICATION_CREATED"
    assert audit.tenant_id == snapshot.tenant_id
    assert audit.entity_id == str(conversation.id)
    assert audit.metadata_json["title"] == "Financeiro"
    assert audit.metadata_json["message"] == "Cliente aguardando pagamento."
    assert audit.metadata_json["priority"] == "normal"
    assert audit.metadata_json["flow_execution_id"] == str(session.id)
    activity = next(item for item in db.added if item.__class__.__name__ == "ConversationLog")
    assert activity.tenant_id == snapshot.tenant_id
    assert activity.conversation_id == conversation.id
    assert activity.intent == "team_notification"
    assert activity.response == "Equipe notificada"
    assert "Financeiro" in activity.message
    assert any(channel == f"dashboard:{snapshot.tenant_id}" and payload["event"] == "team_notification" for channel, payload in published)
    assert any(channel == f"{snapshot.tenant_id}:{conversation.id}" for channel, _payload in published)
    assert any(payload["priority"] == "normal" for _channel, payload in published)


def test_notify_team_high_priority_and_runtime_continues_to_message(monkeypatch) -> None:
    from app.flow_v2 import node_executors

    published = []
    monkeypatch.setattr(node_executors, "sync_publish", lambda channel, payload: published.append((channel, payload)))
    executor, snapshot, _event_store, _session, db = _executor(
        _notify_team_snapshot(
            params={"notification_title": "Financeiro", "notification_message": "Cliente aguardando pagamento.", "notification_priority": "high"},
            with_next=True,
        )
    )
    conversation = _attach_notify_conversation(db, snapshot)

    output = executor.handle_input(db, _input_for_contact(snapshot, contact_id=conversation.contact_id, conversation_id=conversation.id))

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert output.effects == ({"type": "send_message", "text": "Operador avisado"},)
    assert any(payload["priority"] == "high" for _channel, payload in published)


def test_notify_team_respects_tenant_isolation(monkeypatch) -> None:
    from app.flow_v2 import node_executors

    published = []
    monkeypatch.setattr(node_executors, "sync_publish", lambda channel, payload: published.append((channel, payload)))
    executor, snapshot, _event_store, _session, db = _executor(_notify_team_snapshot(params={"notification_message": "Avisar"}))
    conversation = _attach_notify_conversation(db, snapshot, tenant_id=uuid.uuid4())

    output = executor.handle_input(db, _input_for_contact(snapshot, contact_id=conversation.contact_id, conversation_id=conversation.id))

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert not any(item.__class__.__name__ in {"AuditLog", "ConversationLog"} for item in db.added)
    assert published == []



def _create_task_snapshot(*, params=None, with_next=False):
    nodes = [{"id": "action", "type": "action", "data": {"action_type": "create_task", **({"params": params} if params is not None else {})}}]
    edges = []
    if with_next:
        nodes.append({"id": "end", "type": "message", "content": "Tarefa criada com sucesso"})
        edges.append({"id": "e1", "source": "action", "target": "end"})
    return {"schema_version": 1, "start_node_id": "action", "nodes": nodes, "edges": edges}


def _attach_task_conversation(db, snapshot, *, tenant_id=None):
    contact_id = uuid.uuid4()
    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id or snapshot.tenant_id,
        contact_id=contact_id,
        phone_number="+5511999999999",
        name="Cliente Tarefa",
        updated_at=None,
    )
    db.conversation = conversation
    return conversation


def test_create_task_creates_task_audit_log_realtime_and_continues(monkeypatch) -> None:
    from app.flow_v2 import node_executors

    published = []
    monkeypatch.setattr(node_executors, "sync_publish", lambda channel, payload: published.append((channel, payload)))
    executor, snapshot, _event_store, session, db = _executor(
        _create_task_snapshot(
            params={
                "task_title": "Ligar para cliente",
                "task_description": "Confirmar pagamento",
                "task_priority": "high",
                "task_assignee": "Maria",
                "task_due_minutes": "30",
            },
            with_next=True,
        )
    )
    conversation = _attach_task_conversation(db, snapshot)
    lead = SimpleNamespace(id=uuid.uuid4(), tenant_id=snapshot.tenant_id, contact_id=conversation.contact_id, conversation_id=conversation.id, phone="+5511999999999")
    db.lead = lead

    output = executor.handle_input(db, _input_for_contact(snapshot, contact_id=conversation.contact_id, conversation_id=conversation.id))

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert output.effects == ({"type": "send_message", "text": "Tarefa criada com sucesso"},)
    task = next(item for item in db.added if item.__class__.__name__ == "Task")
    assert task.tenant_id == snapshot.tenant_id
    assert task.conversation_id == conversation.id
    assert task.contact_id == conversation.contact_id
    assert task.lead_id == lead.id
    assert task.title == "Ligar para cliente"
    assert task.description == "Confirmar pagamento"
    assert task.priority == "high"
    assert task.status == "open"
    assert task.assigned_to == "Maria"
    assert task.due_at is not None
    assert 29 <= (task.due_at - task.created_at).total_seconds() / 60 <= 31
    audit = next(item for item in db.added if item.__class__.__name__ == "AuditLog")
    assert audit.action == "TASK_CREATED"
    assert audit.tenant_id == snapshot.tenant_id
    assert audit.entity_id == str(task.id)
    assert audit.metadata_json["priority"] == "high"
    assert audit.metadata_json["due_minutes"] == 30
    activity = next(item for item in db.added if item.__class__.__name__ == "ConversationLog")
    assert activity.tenant_id == snapshot.tenant_id
    assert activity.conversation_id == conversation.id
    assert activity.intent == "task_created"
    assert activity.response == "Tarefa criada"
    assert "Ligar para cliente" in activity.message
    assert any(channel == f"dashboard:{snapshot.tenant_id}" and payload["event"] == "task_created" for channel, payload in published)
    assert any(channel == f"{snapshot.tenant_id}:{conversation.id}" for channel, _payload in published)
    assert any(payload["task"]["title"] == "Ligar para cliente" for _channel, payload in published)


def test_create_task_respects_tenant_isolation(monkeypatch) -> None:
    from app.flow_v2 import node_executors

    published = []
    monkeypatch.setattr(node_executors, "sync_publish", lambda channel, payload: published.append((channel, payload)))
    executor, snapshot, _event_store, _session, db = _executor(_create_task_snapshot(params={"task_title": "Isolada"}))
    conversation = _attach_task_conversation(db, snapshot, tenant_id=uuid.uuid4())

    output = executor.handle_input(db, _input_for_contact(snapshot, contact_id=conversation.contact_id, conversation_id=conversation.id))

    assert output.status == FlowV2SessionStatus.COMPLETED
    assert not any(item.__class__.__name__ in {"Task", "AuditLog", "ConversationLog"} for item in db.added)
    assert published == []


def test_create_task_defaults_priority_and_due_minutes(monkeypatch) -> None:
    from app.flow_v2 import node_executors

    monkeypatch.setattr(node_executors, "sync_publish", lambda _channel, _payload: None)
    executor, snapshot, _event_store, _session, db = _executor(_create_task_snapshot(params={"task_title": "Retornar contato"}))
    conversation = _attach_task_conversation(db, snapshot)

    output = executor.handle_input(db, _input_for_contact(snapshot, contact_id=conversation.contact_id, conversation_id=conversation.id))

    assert output.status == FlowV2SessionStatus.COMPLETED
    task = next(item for item in db.added if item.__class__.__name__ == "Task")
    assert task.priority == "normal"
    assert task.due_at is not None
    assert 59 <= (task.due_at - task.created_at).total_seconds() / 60 <= 61


def test_dynamic_template_renders_message_contact_name() -> None:
    executor, snapshot, _event_store, session, db = _executor({"schema_version": 1, "start_node_id": "start", "nodes": [{"id": "start", "type": "message", "data": {"content": "Olá {{ contact.name }}"}}], "edges": []})
    contact_id = uuid.uuid4()
    session.contact_id = contact_id
    db.contact = SimpleNamespace(id=contact_id, tenant_id=snapshot.tenant_id, name="Gabriel", phone="+5511999999999")

    output = executor.handle_input(db, RuntimeInput(tenant_id=snapshot.tenant_id, flow_version_id=snapshot.flow_version_id, external_user_id="whatsapp:+5511999999999", contact_id=contact_id, message_text="oi"))

    assert output.actions[0].as_effect()["text"] == "Olá Gabriel"


def test_dynamic_template_renders_cta_url_and_unknown_as_empty() -> None:
    executor, snapshot, _event_store, session, db = _executor({"schema_version": 1, "start_node_id": "start", "nodes": [{"id": "start", "type": "cta_url", "data": {"text": "Olá {{missing.value}}", "button_text": "Abrir", "url": "https://example.com/{{contact.phone}}"}}], "edges": []})
    contact_id = uuid.uuid4()
    session.contact_id = contact_id
    db.contact = SimpleNamespace(id=contact_id, tenant_id=snapshot.tenant_id, name="Gabriel", phone="5511999999999")

    output = executor.handle_input(db, RuntimeInput(tenant_id=snapshot.tenant_id, flow_version_id=snapshot.flow_version_id, external_user_id="whatsapp:+5511999999999", contact_id=contact_id, message_text="oi"))
    effect = output.actions[0].as_effect()

    assert effect["text"] == "Olá "
    assert effect["url"] == "https://example.com/5511999999999"


def test_dynamic_template_does_not_eval_code() -> None:
    from app.flow_v2.template_renderer import FlowRenderContext, render_template

    rendered = render_template("{{__import__.os}} {{ contact.name.__class__ }}", FlowRenderContext(tenant_id="t", contact={"name": "Gabriel"}))

    assert rendered == " "


def test_template_date_variables_use_pt_br_and_preserve_iso() -> None:
    from datetime import UTC, datetime

    from app.flow_v2.template_renderer import FlowRenderContext, render_template

    context = FlowRenderContext(tenant_id="t", now=datetime(2026, 6, 14, 12, 34, 56, tzinfo=UTC))

    rendered = render_template("{{today}}|{{now}}|{{today_iso}}|{{now_iso}}", context)

    assert rendered == "14/06/2026|14/06/2026 09:34|2026-06-14|2026-06-14T12:34:56+00:00"


def test_publish_accepts_templated_media_and_cta_urls() -> None:
    published = FlowV2Publisher().publish(
        nodes=[
            {"id": "media", "type": "media", "data": {"isStart": True, "media_type": "image", "media_url": "{{contact.media_url}}", "caption": "Olá {{contact.name}}"}},
            {"id": "cta", "type": "cta_url", "data": {"text": "Acesse", "button_text": "Abrir", "url": "{{contact.link}}"}},
        ],
        edges=[{"id": "e1", "source": "media", "target": "cta"}],
    )

    assert published.validation.is_valid


def test_ai_rag_end_flow_finishes_session() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "rag",
        "nodes": [{"id": "rag", "type": "ai_rag", "data": {"question": "{{last_message}}", "fallback_message": "Resposta IA/RAG", "after_answer_behavior": "end_flow", "isStart": True}}],
        "edges": [],
    }
    executor, snapshot, _event_store, _session, db = _executor(raw_snapshot)

    first = executor.handle_input(db, _input_with_text(snapshot, "wamid.ai.end.1", "oi"))
    second = executor.handle_input(db, _input_with_text(snapshot, "wamid.ai.end.2", "nova pergunta"))

    assert first.status == FlowV2SessionStatus.COMPLETED
    assert first.current_node_id is None
    assert [action.as_effect()["text"] for action in first.actions] == ["Resposta IA/RAG"]
    assert second.status == FlowV2SessionStatus.COMPLETED
    assert second.actions == ()


def test_ai_rag_wait_same_node_keeps_session_waiting() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Olá! Como posso te ajudar?", "data": {"wait_for_reply": True}},
            {"id": "rag", "type": "ai_rag", "data": {"question": "{{last_message}}", "fallback_message": "Resposta IA/RAG", "after_answer_behavior": "wait_same_node"}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "rag"}],
    }
    executor, snapshot, event_store, _session, db = _executor(raw_snapshot)

    initial = executor.handle_input(db, _input_with_text(snapshot, "wamid.ai.wait.1", "oi"))
    first_ai = executor.handle_input(db, _input_with_text(snapshot, "wamid.ai.wait.2", "qual o prazo?"))
    second_ai = executor.handle_input(db, _input_with_text(snapshot, "wamid.ai.wait.3", "e documentos?"))

    assert initial.status == FlowV2SessionStatus.WAITING
    assert initial.current_node_id == "rag"
    assert first_ai.status == FlowV2SessionStatus.WAITING
    assert first_ai.current_node_id == "rag"
    assert second_ai.status == FlowV2SessionStatus.WAITING
    assert second_ai.current_node_id == "rag"
    sent_texts = [event["payload"].get("message") for event in event_store.events if event["event_type"] == str(FlowV2EventType.MESSAGE_SENT)]
    assert sent_texts == ["Olá! Como posso te ajudar?", "Resposta IA/RAG", "Resposta IA/RAG"]


def test_ai_rag_initial_node_continuous_chat() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "rag",
        "nodes": [{"id": "rag", "type": "ai_rag", "data": {"isStart": True, "question": "{{last_message}}", "fallback_message": "Resposta IA/RAG", "after_answer_behavior": "wait_same_node"}}],
        "edges": [],
    }
    executor, snapshot, _event_store, _session, db = _executor(raw_snapshot)

    first = executor.handle_input(db, _input_with_text(snapshot, "wamid.ai.initial.1", "oi"))
    second = executor.handle_input(db, _input_with_text(snapshot, "wamid.ai.initial.2", "outra dúvida"))

    assert first.status == FlowV2SessionStatus.WAITING
    assert first.current_node_id == "rag"
    assert second.status == FlowV2SessionStatus.WAITING
    assert second.current_node_id == "rag"
    assert [action.as_effect()["text"] for action in first.actions] == ["Resposta IA/RAG"]
    assert [action.as_effect()["text"] for action in second.actions] == ["Resposta IA/RAG"]


def test_message_wait_for_reply_then_ai_rag_wait_same_node() -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "start",
        "nodes": [
            {"id": "start", "type": "message", "content": "Escolha uma área", "data": {"wait_for_reply": True}},
            {"id": "rag", "type": "ai_rag", "data": {"question": "{{last_message}}", "fallback_message": "Resposta IA/RAG", "after_answer_behavior": "wait_same_node"}},
        ],
        "edges": [{"id": "e1", "source": "start", "target": "rag"}],
    }
    executor, snapshot, event_store, _session, db = _executor(raw_snapshot)

    greeting = executor.handle_input(db, _input_with_text(snapshot, "wamid.hybrid.1", "oi"))
    area_answer = executor.handle_input(db, _input_with_text(snapshot, "wamid.hybrid.2", "saúde"))
    follow_up = executor.handle_input(db, _input_with_text(snapshot, "wamid.hybrid.3", "horário?"))

    assert greeting.status == FlowV2SessionStatus.WAITING
    assert area_answer.status == FlowV2SessionStatus.WAITING
    assert follow_up.status == FlowV2SessionStatus.WAITING
    assert follow_up.current_node_id == "rag"
    sent_texts = [event["payload"].get("message") for event in event_store.events if event["event_type"] == str(FlowV2EventType.MESSAGE_SENT)]
    assert sent_texts == ["Escolha uma área", "Resposta IA/RAG", "Resposta IA/RAG"]


def test_ai_agent_terminal_wait_same_node_processes_follow_up_without_restart_block(caplog, monkeypatch) -> None:
    from app.flow_v2.executors import _legacy as legacy_executors
    from app.services.ai_agent_service import AgentRunResult, AgentToolAction

    def fake_run_agent(*_args, **_kwargs):
        return AgentRunResult(
            message="Resposta do agente",
            actions=[AgentToolAction(type="message", data={"message": "Resposta do agente"})],
            tools_used=[],
            steps_count=1,
            final_tool="responder",
            status="success",
            fallback_used=False,
            metadata={},
        )

    monkeypatch.setattr(legacy_executors, "run_agent_for_tenant", fake_run_agent)
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "agent",
        "nodes": [
            {
                "id": "agent",
                "type": "ai_agent",
                "data": {
                    "isStart": True,
                    "is_terminal": True,
                    "endFlow": True,
                    "input_template": "{{last_message}}",
                    "allowed_tools": ["responder"],
                    "after_agent_behavior": "wait_same_node",
                    "allow_mcp_tools": True,
                    "mcp_tool_ids": [],
                },
            }
        ],
        "edges": [],
    }
    executor, snapshot, event_store, _session, db = _executor(raw_snapshot)

    with caplog.at_level("INFO"):
        first = executor.handle_input(db, _input_with_text(snapshot, "wamid.agent.wait.1", "oi"))
        second = executor.handle_input(db, _input_with_text(snapshot, "wamid.agent.wait.2", "outra pergunta"))

    assert first.status == FlowV2SessionStatus.WAITING
    assert first.current_node_id == "agent"
    assert second.status == FlowV2SessionStatus.WAITING
    assert second.current_node_id == "agent"
    assert [action.as_effect()["text"] for action in first.actions] == ["Resposta do agente"]
    assert [action.as_effect()["text"] for action in second.actions] == ["Resposta do agente"]
    sent_texts = [event["payload"].get("message") for event in event_store.events if event["event_type"] == str(FlowV2EventType.MESSAGE_SENT)]
    assert sent_texts == []
    assert "SESSION RESTART BLOCKED" not in caplog.text
    assert "ignore_future_message_auto_restart_disabled" not in caplog.text


def test_ai_system_continuous_terminal_nodes_wait_at_dispatcher_and_reprocess_next_message(caplog) -> None:
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "dispatcher",
        "nodes": [
            {"id": "dispatcher", "type": "ai_dispatcher", "data": {"compiled_from_ai_system": "sys", "ai_system_internal_type": "ai_dispatcher"}},
            {"id": "greeting", "type": "ai_greeting", "is_terminal": True, "data": {"compiled_from_ai_system": "sys", "ai_system_internal_type": "ai_greeting", "endFlow": True}},
            {"id": "calendar", "type": "ai_safe_fallback", "is_terminal": True, "data": {"compiled_from_ai_system": "sys", "ai_system_internal_type": "ai_calendar_agent", "fallback_message": "calendar called", "endFlow": True}},
            {"id": "fallback", "type": "ai_safe_fallback", "is_terminal": True, "data": {"compiled_from_ai_system": "sys", "ai_system_internal_type": "ai_safe_fallback", "endFlow": True}},
        ],
        "edges": [
            {"id": "e-greeting", "source": "dispatcher", "target": "greeting", "sourceHandle": "greeting"},
            {"id": "e-calendar", "source": "dispatcher", "target": "calendar", "sourceHandle": "calendar_create"},
            {"id": "e-unknown", "source": "dispatcher", "target": "fallback", "sourceHandle": "unknown"},
        ],
    }
    executor, snapshot, event_store, _session, db = _executor(raw_snapshot)

    with caplog.at_level("INFO"):
        first = executor.handle_input(db, _input_with_text(snapshot, "wamid.ai_system.1", "oi"))
        second = executor.handle_input(db, _input_with_text(snapshot, "wamid.ai_system.2", "Marque uma Call Online com o Gustavo amanhã as 13:30"))

    assert first.status == FlowV2SessionStatus.WAITING
    assert first.current_node_id == "dispatcher"
    assert second.status == FlowV2SessionStatus.WAITING
    assert second.current_node_id == "dispatcher"
    assert [action.as_effect()["text"] for action in first.actions] == ["Olá! 👋 Como posso ajudar?"]
    assert [action.as_effect()["text"] for action in second.actions] == ["calendar called"]
    routed_events = [event for event in event_store.events if event["payload"].get("analytics_event") == "AI_DISPATCHER_ROUTED"]
    assert [event["payload"].get("intent") for event in routed_events] == ["greeting", "calendar_create"]
    assert "AI_SYSTEM_SESSION_WAITING_AT_DISPATCHER" in caplog.text
    assert "AI_SYSTEM_RESUME_AT_DISPATCHER" not in caplog.text


def test_ai_system_pending_slot_context_keeps_calendar_agent_node(caplog, monkeypatch) -> None:
    from app.flow_v2.executors import _legacy as legacy_executors
    from app.services.ai_agent_service import AgentRunResult, AgentToolAction

    def fake_run_agent(*_args, **_kwargs):
        return AgentRunResult(
            message="Qual data?",
            actions=[AgentToolAction(type="message", data={"message": "Qual data?"})],
            tools_used=[],
            steps_count=1,
            final_tool="responder",
            status="success",
            fallback_used=False,
            metadata={},
        )

    monkeypatch.setattr(legacy_executors, "run_agent_for_tenant", fake_run_agent)
    raw_snapshot = {
        "schema_version": 1,
        "start_node_id": "dispatcher",
        "nodes": [
            {"id": "dispatcher", "type": "ai_dispatcher", "data": {"compiled_from_ai_system": "sys", "ai_system_internal_type": "ai_dispatcher"}},
            {"id": "calendar", "type": "ai_agent", "is_terminal": True, "data": {"compiled_from_ai_system": "sys", "ai_system_internal_type": "ai_calendar_agent", "after_agent_behavior": "wait_same_node", "endFlow": True}},
        ],
        "edges": [{"id": "e-calendar", "source": "dispatcher", "target": "calendar", "sourceHandle": "calendar_create"}],
    }
    executor, snapshot, _event_store, session, db = _executor(raw_snapshot)
    session.current_node_id = "calendar"
    session.status = FlowV2SessionStatus.WAITING
    session.variables = {"pending_slot": "date"}

    with caplog.at_level("INFO"):
        result = executor.handle_input(db, _input_with_text(snapshot, "wamid.ai_system.slot.1", "amanhã"))

    assert result.status == FlowV2SessionStatus.WAITING
    assert result.current_node_id == "calendar"
    assert [action.as_effect()["text"] for action in result.actions] == ["Qual data?"]
    assert "AI_SYSTEM_KEEP_SLOT_CONTEXT" in caplog.text
    assert "AI_SYSTEM_RESUME_AT_DISPATCHER" not in caplog.text


def test_ai_system_terminal_canvas_node_waits_and_internal_events_use_unique_indexes(caplog) -> None:
    raw_snapshot = {
        "nodes": [
            {
                "id": "system",
                "type": "ai_system",
                "is_terminal": True,
                "data": {
                    "end": True,
                    "isEnd": True,
                    "terminal": True,
                    "internal_nodes": [
                        {"id": "greeting", "type": "message", "isStart": True, "is_terminal": True, "data": {"text": "Olá! 👋 Como posso ajudar?", "endFlow": True}}
                    ],
                    "internal_edges": [],
                },
            }
        ],
        "edges": [],
        "start_node_id": "system",
    }
    executor, snapshot, event_store, session, db = _executor(raw_snapshot)

    with caplog.at_level("INFO"):
        first = executor.handle_input(db, _input_with_text(snapshot, "wamid.ai_system.outer.1", "OI"))
        second = executor.handle_input(db, _input_with_text(snapshot, "wamid.ai_system.outer.2", "Marque uma call amanhã às 13:30"))

    assert [action.text for action in first.actions] == ["Olá! 👋 Como posso ajudar?"]
    assert [action.text for action in second.actions] == ["Olá! 👋 Como posso ajudar?"]
    assert first.status == FlowV2SessionStatus.WAITING
    assert first.current_node_id == "system"
    assert second.status == FlowV2SessionStatus.WAITING
    assert second.current_node_id == "system"
    assert session.context["ai_system_internal_runtime"]["system"]["current_node_id"] == "greeting"
    event_indexes = [event["event_index"] for event in event_store.events]
    assert len(event_indexes) == len(set(event_indexes))
    assert event_indexes == list(range(1, len(event_indexes) + 1))
    assert "terminal_node_marked_end_flow" not in caplog.text


def test_choice_to_data_collection_reply_uses_success_output_without_repeating_prompt(monkeypatch) -> None:
    monkeypatch.setattr("app.services.appointment_policy_service.policy_for_tenant", lambda db, tenant_id: {})
    raw_snapshot = {
        'schema_version': 1,
        'start_node_id': 'choice',
        'nodes': [
            {'id': 'choice', 'type': 'choice', 'data': {'isStart': True, 'content': 'O que deseja?', 'options': [{'id': 'quero_planos', 'label': 'Planos'}]}},
            {'id': 'collect', 'type': 'data_collection', 'data': {'prompt': 'Qual período?', 'variable_name': 'appointment_period', 'data_type': 'appointment_period'}},
            {'id': 'done', 'type': 'message', 'data': {'content': 'Período: {{appointment_period}}'}},
        ],
        'edges': [
            {'id': 'choice-collect', 'source': 'choice', 'sourceHandle': 'quero_planos', 'target': 'collect'},
            {'id': 'collect-done', 'source': 'collect', 'sourceHandle': 'success', 'target': 'done'},
        ],
    }
    executor, snapshot, _events, session, db = _executor(raw_snapshot)
    session.current_node_id = 'choice'
    executor.handle_input(db, _input_with_id(snapshot, 'initial-choice'))

    waiting = executor.handle_input(db, _input_with_id(snapshot, 'choice-reply', {'row_id': 'quero_planos'}))
    prompts = [action for action in waiting.actions if isinstance(action, SendMessageAction) and action.text == 'Qual período?']
    assert waiting.status == FlowV2SessionStatus.WAITING
    assert len(prompts) == 1
    assert session.context['waiting_variable'] == 'appointment_period'

    completed = executor.handle_input(db, _input_with_text(snapshot, 'period-reply', 'amanhã de manhã'))
    assert all(not isinstance(action, SendMessageAction) or action.text != 'Qual período?' for action in completed.actions)
    assert session.variables['appointment_period']['mode'] == 'period'
    assert session.variables['appointment_period']['window_start']
    assert completed.status == FlowV2SessionStatus.COMPLETED
