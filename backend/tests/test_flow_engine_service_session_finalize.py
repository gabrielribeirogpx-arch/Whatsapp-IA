from __future__ import annotations

import os
import uuid
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.services import flow_engine_service


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value


class _ExecuteResult:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return _ScalarResult(self.value)


class _FakeDB:
    def __init__(self, conversation):
        self.conversation = conversation
        self.added = []
        self.commits = 0

    def execute(self, _statement):
        return _ExecuteResult(self.conversation)

    def add(self, value):
        self.added.append(value)

    def commit(self):
        self.commits += 1


class _SessionService:
    def __init__(self, _db, runtime_session):
        self.runtime_session = runtime_session

    def get_runtime_session_state(self, **_kwargs):
        return {
            "session": self.runtime_session,
            "exists": True,
            "status": self.runtime_session.status,
            "is_active": True,
            "is_finalized": False,
        }


def test_process_flow_engine_does_not_reopen_session_finalized_during_continuation(monkeypatch):
    tenant_id = uuid.uuid4()
    flow_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    condition_node_id = uuid.uuid4()
    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        phone_number="5511999990001",
        context={},
        retries=0,
        current_node_id=None,
        mode="bot",
        current_flow=None,
    )
    runtime_session = SimpleNamespace(
        id=uuid.uuid4(),
        status="running",
        current_node_id=condition_node_id,
        variables={"current_node_id": str(condition_node_id)},
        flow_version_id=flow_version_id,
    )
    db = _FakeDB(conversation)
    flow = SimpleNamespace(id=flow_id, published_version_id=flow_version_id)
    runtime_graph = {"nodes": [{"id": str(condition_node_id), "type": "condition"}], "edges": []}

    monkeypatch.setattr(flow_engine_service, "FlowSessionService", lambda _db: _SessionService(_db, runtime_session))
    monkeypatch.setattr(flow_engine_service, "get_active_visual_flow", lambda **_kwargs: flow)
    monkeypatch.setattr(flow_engine_service, "is_flow_trigger", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(flow_engine_service, "_get_current_flow_runtime", lambda **_kwargs: runtime_graph)
    monkeypatch.setattr(flow_engine_service, "_get_node", lambda **_kwargs: {"id": str(condition_node_id), "type": "condition"})

    def _finalizing_run_until_wait_node(**_kwargs):
        runtime_session.status = "completed"
        runtime_session.current_node_id = None
        return None

    monkeypatch.setattr(flow_engine_service, "run_until_wait_node", _finalizing_run_until_wait_node)

    flow_engine_service.process_flow_engine(
        db=db,
        tenant_id=tenant_id,
        phone="5511999990001",
        message_text="suporte",
    )

    assert runtime_session.status == "completed"
    assert runtime_session.current_node_id is None
    assert db.commits == 1


def test_process_flow_engine_preserves_running_condition_session_from_variables_on_trigger(monkeypatch):
    tenant_id = uuid.uuid4()
    flow_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    condition_node_id = uuid.uuid4()
    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        phone_number="5511999990002",
        context={},
        retries=0,
        current_node_id=None,
        mode="bot",
        current_flow=None,
    )
    runtime_session = SimpleNamespace(
        id=uuid.uuid4(),
        status="running",
        current_node_id=None,
        variables={"current_node_id": str(condition_node_id)},
        flow_version_id=flow_version_id,
    )
    db = _FakeDB(conversation)
    flow = SimpleNamespace(id=flow_id, published_version_id=flow_version_id)
    runtime_graph = {"nodes": [{"id": str(condition_node_id), "type": "condition"}], "edges": []}
    run_calls = []

    class _InactiveStateSessionService:
        def __init__(self, _db):
            self.runtime_session = runtime_session

        def get_runtime_session_state(self, **_kwargs):
            return {
                "session": self.runtime_session,
                "exists": True,
                "status": self.runtime_session.status,
                "is_active": False,
                "is_finalized": True,
            }

        def end_session(self, *_args, **_kwargs):
            raise AssertionError("running condition sessions must not be abandoned")

    monkeypatch.setattr(flow_engine_service, "FlowSessionService", _InactiveStateSessionService)
    monkeypatch.setattr(flow_engine_service, "get_active_visual_flow", lambda **_kwargs: flow)
    monkeypatch.setattr(flow_engine_service, "is_flow_trigger", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(flow_engine_service, "_get_current_flow_runtime", lambda **_kwargs: runtime_graph)
    monkeypatch.setattr(flow_engine_service, "_get_node", lambda **_kwargs: {"id": str(condition_node_id), "type": "condition"})

    def _recording_run_until_wait_node(**kwargs):
        run_calls.append(kwargs)
        runtime_session.current_node_id = condition_node_id
        return None

    monkeypatch.setattr(flow_engine_service, "run_until_wait_node", _recording_run_until_wait_node)

    flow_engine_service.process_flow_engine(
        db=db,
        tenant_id=tenant_id,
        phone="5511999990002",
        message_text="vendas",
    )

    assert len(run_calls) == 1
    assert run_calls[0]["start_node_id"] == condition_node_id
    assert runtime_session.status == "running"
    assert runtime_session.current_node_id == condition_node_id
    assert db.commits == 1


def test_run_until_wait_node_resends_choice_when_waiting_without_selection(monkeypatch, caplog):
    tenant_id = uuid.uuid4()
    flow_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    choice_node_id = uuid.uuid4()
    sales_node_id = uuid.uuid4()
    conversation = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        phone_number="5511999990003",
        user_identifier=None,
        context={"waiting_choice": True, "choice_node_id": str(choice_node_id)},
        retries=0,
        current_node_id=choice_node_id,
        mode="bot",
        current_flow=None,
    )
    runtime_session = SimpleNamespace(
        id=uuid.uuid4(),
        status="running",
        current_node_id=choice_node_id,
        context={"waiting_choice": True, "choice_node_id": str(choice_node_id)},
        variables={},
        flow_version_id=flow_version_id,
    )
    choice_node = {
        "id": str(choice_node_id),
        "type": "choice",
        "content": "Posso te mostrar nossos planos.",
        "data": {
            "buttons": [
                {"label": "Plano Básico", "handleId": "basic"},
                {"label": "Plano Pro", "handleId": "pro"},
            ]
        },
    }
    runtime_graph = {
        "node_map": {str(choice_node_id): choice_node},
        "edges": [{"source": str(choice_node_id), "target": str(sales_node_id), "sourceHandle": "basic"}],
    }
    sent_lists = []
    safe_updates = []

    class _RuntimeSessionService:
        def __init__(self, _db):
            pass

        def get_runtime_session(self, tenant_id, user_identifier, flow):
            return runtime_session, None

        def safe_update_current_node(self, *, session, next_node_id, reason, graph_context):
            safe_updates.append({"next_node_id": next_node_id, "reason": reason, "graph_context": graph_context})
            return next_node_id

    class _RunDB(_FakeDB):
        def get(self, _model, key):
            return SimpleNamespace(id=key)

    db = _RunDB(conversation)
    flow = SimpleNamespace(id=flow_id, published_version_id=flow_version_id)

    monkeypatch.setattr(flow_engine_service, "FlowSessionService", _RuntimeSessionService)
    monkeypatch.setattr(flow_engine_service, "_emit_node_entered_event", lambda **_kwargs: None)
    monkeypatch.setattr(flow_engine_service, "_emit_runtime_event", lambda **_kwargs: None)
    monkeypatch.setattr(flow_engine_service, "_send_flow_interactive_list", lambda **kwargs: sent_lists.append(kwargs))
    monkeypatch.setattr(
        flow_engine_service,
        "_send_flow_whatsapp_message",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("choice resume must not send a downstream text node")),
    )

    caplog.set_level("WARNING", logger=flow_engine_service.logger.name)

    result = flow_engine_service.run_until_wait_node(
        db=db,
        flow=flow,
        runtime_graph=runtime_graph,
        session=conversation,
        start_node_id=choice_node_id,
        incoming_text="ainda não escolhi",
    )

    assert result == choice_node
    assert len(sent_lists) == 1
    assert sent_lists[0]["text"] == "Posso te mostrar nossos planos."
    assert sent_lists[0]["sections"][0]["rows"] == [
        {"id": "basic", "title": "Plano Básico"},
        {"id": "pro", "title": "Plano Pro"},
    ]
    assert runtime_session.current_node_id == choice_node_id
    assert runtime_session.context["waiting_choice"] is True
    assert conversation.context["flow_current_node_id"] == str(choice_node_id)
    assert safe_updates == [
        {
            "next_node_id": choice_node_id,
            "reason": "waiting_choice",
            "graph_context": {"executed_node_id": str(choice_node_id)},
        }
    ]
    assert "[CHOICE RESUME NO_SELECTION_RESEND]" in caplog.text
