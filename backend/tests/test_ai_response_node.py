from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.flow_v2.contracts import RuntimeInput
from app.flow_v2.graph_validator import FlowV2GraphValidator, GraphValidationStatus
from app.flow_v2.node_executors import AiResponseNodeExecutor
from app.flow_v2.snapshot import FlowV2Snapshot


class EventStore:
    def __init__(self):
        self.events = []

    def append(self, *args, **kwargs):
        self.events.append(kwargs)


class Resolver:
    def resolve(self, db, *, snapshot, session, source_node_id, source_handle=None):
        return SimpleNamespace(target_node_id="next")


class DB:
    def __init__(self, flow_id):
        self.flow_id = flow_id
        self.added = []

    def get(self, model, item_id):
        return SimpleNamespace(flow_id=self.flow_id)

    def add(self, item):
        self.added.append(item)


def _runtime(node_data, edges=()):
    flow_id = uuid.uuid4()
    tenant_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    node_id = "ai"
    nodes = ({"id": node_id, "type": "ai_response", "data": node_data}, {"id": "next", "type": "message", "data": {"content": "ok"}})
    snapshot = FlowV2Snapshot(flow_version_id=flow_version_id, tenant_id=tenant_id, hash="h", nodes=nodes, edges=edges, start_node_id=node_id)
    session = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, flow_version_id=flow_version_id)
    runtime_input = RuntimeInput(tenant_id=tenant_id, flow_version_id=flow_version_id, external_user_id="whatsapp:+55", message_text="Olá", metadata={"message_id": "m1"})
    return DB(flow_id), snapshot, session, runtime_input


def test_ai_response_simple_uses_tenant_provider_and_no_rag(monkeypatch):
    import app.flow_v2.node_executors as node_executors

    captured = {}

    def fake_generate(db, tenant_id, messages, options=None):
        captured.update({"tenant_id": tenant_id, "messages": messages, "options": options})
        return "Olá! Como posso ajudar?"

    monkeypatch.setattr(node_executors, "generate_answer_for_tenant", fake_generate)
    monkeypatch.setattr(node_executors, "answer_with_rag", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("RAG must not be used")))

    db, snapshot, session, runtime_input = _runtime({"question": "{{last_message}}", "memory_enabled": False, "model_override": "gpt-4o-mini"})
    result = AiResponseNodeExecutor(event_store=EventStore(), transition_resolver=Resolver()).execute(db, snapshot=snapshot, session=session, node=snapshot.nodes[0], runtime_input=runtime_input)

    assert result.status == "complete"
    assert result.actions[0].text == "Olá! Como posso ajudar?"
    assert captured["tenant_id"] == session.tenant_id
    assert captured["messages"][-1] == {"role": "user", "content": "Olá"}
    assert captured["options"]["chat_model"] == "gpt-4o-mini"


def test_ai_response_memory_enabled_saves_user_and_assistant(monkeypatch):
    import app.flow_v2.node_executors as node_executors

    calls = {"user": 0, "assistant": 0, "history": 0}

    class Memory:
        def append_user_message(self, *args, **kwargs):
            calls["user"] += 1
        def append_assistant_message(self, *args, **kwargs):
            calls["assistant"] += 1
            assert kwargs["metadata"]["is_first_ai_turn"] is False
        def get_recent_history(self, *args, **kwargs):
            calls["history"] += 1
            return [SimpleNamespace(role="user", content="Olá"), SimpleNamespace(role="assistant", content="Oi")]
        def build_history_for_prompt(self, messages):
            return "Usuário: Olá\nIA: Oi"

    monkeypatch.setattr(node_executors, "flow_ai_memory_service", Memory())
    monkeypatch.setattr(node_executors, "generate_answer_for_tenant", lambda *args, **kwargs: "Resposta com memória")

    db, snapshot, session, runtime_input = _runtime({"memory_enabled": True})
    result = AiResponseNodeExecutor(event_store=EventStore(), transition_resolver=Resolver()).execute(db, snapshot=snapshot, session=session, node=snapshot.nodes[0], runtime_input=runtime_input)

    assert result.actions[0].metadata["is_first_ai_turn"] is False
    assert calls == {"user": 1, "assistant": 1, "history": 1}


def test_ai_response_memory_disabled_does_not_read_history(monkeypatch):
    import app.flow_v2.node_executors as node_executors

    class Memory:
        def append_user_message(self, *args, **kwargs):
            raise AssertionError("memory disabled")
        def append_assistant_message(self, *args, **kwargs):
            raise AssertionError("memory disabled")
        def get_recent_history(self, *args, **kwargs):
            raise AssertionError("memory disabled")

    monkeypatch.setattr(node_executors, "flow_ai_memory_service", Memory())
    monkeypatch.setattr(node_executors, "generate_answer_for_tenant", lambda *args, **kwargs: "Sem memória")

    db, snapshot, session, runtime_input = _runtime({"memory_enabled": False})
    result = AiResponseNodeExecutor(event_store=EventStore(), transition_resolver=Resolver()).execute(db, snapshot=snapshot, session=session, node=snapshot.nodes[0], runtime_input=runtime_input)

    assert result.actions[0].text == "Sem memória"


def test_ai_response_after_answer_behaviors(monkeypatch):
    import app.flow_v2.node_executors as node_executors

    monkeypatch.setattr(node_executors, "generate_answer_for_tenant", lambda *args, **kwargs: "ok")

    db, snapshot, session, runtime_input = _runtime({"after_answer_behavior": "wait_same_node", "memory_enabled": False})
    result = AiResponseNodeExecutor(event_store=EventStore(), transition_resolver=Resolver()).execute(db, snapshot=snapshot, session=session, node=snapshot.nodes[0], runtime_input=runtime_input)
    assert result.status == "wait"
    assert result.next_node_id == "ai"

    db, snapshot, session, runtime_input = _runtime({"after_answer_behavior": "continue_to_next", "memory_enabled": False}, edges=({"id": "e", "source_node_id": "ai", "target_node_id": "next"},))
    result = AiResponseNodeExecutor(event_store=EventStore(), transition_resolver=Resolver()).execute(db, snapshot=snapshot, session=session, node=snapshot.nodes[0], runtime_input=runtime_input)
    assert result.status == "continue"
    assert result.next_node_id == "next"


def test_ai_response_validation_matches_ai_rag_edge_rules():
    validator = FlowV2GraphValidator()

    valid = validator.validate(nodes=[{"id": "start", "type": "ai_response", "data": {"isStart": True, "after_answer_behavior": "end_flow"}}], edges=[])
    assert valid.status == GraphValidationStatus.VALID

    wait = validator.validate(nodes=[{"id": "start", "type": "ai_response", "data": {"isStart": True, "after_answer_behavior": "wait_same_node"}}], edges=[])
    assert wait.status == GraphValidationStatus.VALID

    invalid = validator.validate(nodes=[{"id": "start", "type": "ai_response", "data": {"isStart": True, "after_answer_behavior": "continue_to_next"}}], edges=[])
    assert invalid.status == GraphValidationStatus.INVALID
    assert "FLOW_V2_AI_RESPONSE_CONTINUE_TO_NEXT_REQUIRES_EDGE:start" in invalid.errors
