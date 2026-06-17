from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.flow_v2.contracts import RuntimeInput
from app.flow_v2.graph_validator import FlowV2GraphValidator, GraphValidationStatus
from app.flow_v2.node_executors import AiSummaryNodeExecutor
from app.flow_v2.snapshot import FlowV2Snapshot


class EventStore:
    def append(self, *args, **kwargs):
        pass


class Resolver:
    def resolve(self, db, *, snapshot, session, source_node_id, source_handle=None):
        return SimpleNamespace(target_node_id="next")


class DB:
    def __init__(self):
        self.added = []
    def add(self, item):
        self.added.append(item)


def _runtime(node_data, edges=({"id": "e", "source_node_id": "ai", "target_node_id": "next"},)):
    tenant_id = uuid.uuid4()
    flow_version_id = uuid.uuid4()
    nodes = ({"id": "ai", "type": "ai_summary", "data": node_data}, {"id": "next", "type": "message", "data": {"content": "ok"}})
    snapshot = FlowV2Snapshot(flow_version_id=flow_version_id, tenant_id=tenant_id, hash="h", nodes=nodes, edges=edges, start_node_id="ai")
    session = SimpleNamespace(id=uuid.uuid4(), tenant_id=tenant_id, flow_version_id=flow_version_id, context={})
    runtime_input = RuntimeInput(tenant_id=tenant_id, flow_version_id=flow_version_id, external_user_id="whatsapp:+55", message_text="Olá", metadata={"message_id": "m1"})
    return DB(), snapshot, session, runtime_input


def test_ai_summary_uses_history_and_saves_default(monkeypatch):
    import app.flow_v2.node_executors as node_executors

    captured = {}

    class Memory:
        def get_recent_history(self, *args, **kwargs):
            captured["history_kwargs"] = kwargs
            return [SimpleNamespace(role="user", content="Quero comprar"), SimpleNamespace(role="assistant", content="Qual produto?")]
        def build_history_for_prompt(self, messages):
            return "Usuário: Quero comprar\nAssistente: Qual produto?"

    def fake_summary(db, tenant_id, source_text, instruction=None, summary_format="handoff", options=None):
        captured.update({"tenant_id": tenant_id, "source_text": source_text, "format": summary_format, "options": options})
        return "Resumo do atendimento:\nCliente quer comprar."

    monkeypatch.setattr(node_executors, "flow_ai_memory_service", Memory())
    monkeypatch.setattr(node_executors, "summarize_for_tenant", fake_summary)

    db, snapshot, session, runtime_input = _runtime({"summary_source": "conversation_history"})
    result = AiSummaryNodeExecutor(event_store=EventStore(), transition_resolver=Resolver()).execute(db, snapshot=snapshot, session=session, node=snapshot.nodes[0], runtime_input=runtime_input)

    assert result.status == "continue"
    assert result.actions == ()
    assert session.context["ai"]["summary"].startswith("Resumo")
    assert captured["history_kwargs"]["max_messages"] == 30
    assert captured["tenant_id"] == session.tenant_id


def test_ai_summary_custom_output_and_send_message(monkeypatch):
    import app.flow_v2.node_executors as node_executors

    captured = {}
    def fake_summary(db, tenant_id, source_text, **kwargs):
        captured["source_text"] = source_text
        return "Resumo customizado"

    monkeypatch.setattr(node_executors, "summarize_for_tenant", fake_summary)
    db, snapshot, session, runtime_input = _runtime({"summary_source": "custom_text", "input_template": "Mensagem: {{last_message}}", "output_variable": "crm.note", "send_message": True})
    result = AiSummaryNodeExecutor(event_store=EventStore(), transition_resolver=Resolver()).execute(db, snapshot=snapshot, session=session, node=snapshot.nodes[0], runtime_input=runtime_input)

    assert captured["source_text"] == "Mensagem: Olá"
    assert session.context["ai"]["summary"] == "Resumo customizado"
    assert session.context["crm"]["note"] == "Resumo customizado"
    assert result.actions[0].text == "Resumo customizado"


def test_ai_summary_continue_on_error_true_continues(monkeypatch):
    import app.flow_v2.node_executors as node_executors

    monkeypatch.setattr(node_executors, "summarize_for_tenant", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
    db, snapshot, session, runtime_input = _runtime({"summary_source": "custom_text", "input_template": "x", "continue_on_error": True})
    result = AiSummaryNodeExecutor(event_store=EventStore(), transition_resolver=Resolver()).execute(db, snapshot=snapshot, session=session, node=snapshot.nodes[0], runtime_input=runtime_input)

    assert result.status == "continue"
    assert result.next_node_id == "next"
    assert session.context["ai"]["error"]["error"] == "ai_summary_failed"


def test_ai_summary_validation_rejects_api_key_and_invalid_config():
    validator = FlowV2GraphValidator()
    result = validator.validate(nodes=[{"id": "start", "type": "ai_summary", "data": {"isStart": True, "summary_source": "custom_text", "input_template": "", "summary_format": "bad", "output_variable": "bad name", "api_key": "secret"}}], edges=[])

    assert result.status == GraphValidationStatus.INVALID
    assert "FLOW_V2_AI_NODE_API_KEY_FORBIDDEN:start" in result.errors
    assert "FLOW_V2_AI_SUMMARY_INPUT_TEMPLATE_REQUIRED:start" in result.errors
    assert "FLOW_V2_AI_SUMMARY_FORMAT_INVALID:start" in result.errors
    assert "FLOW_V2_AI_OUTPUT_VARIABLE_INVALID:start" in result.errors
