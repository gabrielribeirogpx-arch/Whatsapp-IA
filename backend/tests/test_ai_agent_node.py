import uuid

from app.flow_v2.graph_validator import FlowV2GraphValidator, GraphValidationStatus
from app.services import ai_agent_service as svc


def test_ai_agent_responde_using_tool(monkeypatch):
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: '{"thought_summary":"ok","tool":"responder","arguments":{"message":"Olá!"}}')
    result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "oi", "instr", ["responder"], {}, options={"max_steps": 1})
    assert result.message == "Olá!"
    assert result.actions[0].type == "message"


def test_ai_agent_definir_variavel(monkeypatch):
    calls = iter([
        '{"thought_summary":"salvar","tool":"definir_variavel","arguments":{"name":"lead.interesse","value":"casamento"}}',
        '{"thought_summary":"ok","tool":"responder","arguments":{"message":"salvei"}}',
    ])
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: next(calls))
    result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "oi", "instr", ["definir_variavel", "responder"], {}, options={"max_steps": 2})
    assert result.actions[0].type == "set_variable"
    assert result.actions[0].data["name"] == "lead.interesse"


def test_ai_agent_rejects_unallowed_tool(monkeypatch):
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: '{"thought_summary":"x","tool":"chamar_webhook","arguments":{"webhook_id":"x"}}')
    result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "oi", "instr", ["responder"], {}, options={"max_steps": 1, "fallback_message": "fallback"})
    assert result.fallback_used is True
    assert result.message == "fallback"


def test_ai_agent_invalid_json_fallback(monkeypatch):
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: 'not json')
    result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "oi", "instr", ["responder"], {}, options={"fallback_message": "fallback"})
    assert result.message == "fallback"


def test_ai_agent_validator_blocks_internal_webhook_and_requires_edge_for_continue():
    validator = FlowV2GraphValidator()
    nodes = [
        {"id": "agent", "type": "ai_agent", "data": {"isStart": True, "allowed_tools": ["chamar_webhook"], "max_steps": 3, "after_agent_behavior": "continue_to_next", "webhooks": [{"id": "x", "url": "https://127.0.0.1/hook", "method": "POST"}]}},
    ]
    result = validator.validate(nodes=nodes, edges=[])
    assert result.status == GraphValidationStatus.INVALID
    assert "FLOW_V2_AI_AGENT_WEBHOOK_URL_INVALID:agent:0" in result.errors
    assert "FLOW_V2_AI_AGENT_CONTINUE_TO_NEXT_REQUIRES_EDGE:agent" in result.errors


def test_ai_agent_validator_blocks_secret_in_config():
    result = FlowV2GraphValidator().validate(nodes=[{"id": "agent", "type": "ai_agent", "data": {"isStart": True, "allowed_tools": ["responder"], "api_key": "sk-test"}}], edges=[])
    assert "FLOW_V2_AI_NODE_API_KEY_FORBIDDEN:agent" in result.errors


def test_ai_agent_mcp_calculate_result_text_used_in_final_response(monkeypatch):
    calls = iter([
        '{"thought_summary":"calcular","tool":"chamar_mcp","arguments":{"tool_id":"calculate","input":{"expression":"1234 * 567"}}}',
        '{"thought_summary":"responder","tool":"responder","arguments":{"message":"O resultado é 699678."}}',
    ])
    seen_messages = []

    def fake_llm(_db, _tenant_id, messages, options=None):
        seen_messages.append(messages)
        return next(calls)

    def fake_mcp_executor(tool, args):
        assert tool["tool_id"] == "calculate"
        assert args == {"expression": "1234 * 567"}
        return {"ok": True, "status": "success", "result": {"content": [{"type": "text", "text": "699678"}]}, "latency_ms": 1}

    monkeypatch.setattr(svc, "generate_answer_for_tenant", fake_llm)
    result = svc.run_agent_for_tenant(
        object(),
        uuid.uuid4(),
        "calcule 1234 * 567",
        "Use a ferramenta calculate para cálculos.",
        ["chamar_mcp", "responder"],
        {"mcp_tools": [{"tool_id": "calculate", "name": "calculate", "description": "Calculadora"}]},
        options={"max_steps": 2, "fallback_message": "fallback"},
        mcp_tool_executor=fake_mcp_executor,
    )

    assert result.fallback_used is False
    assert result.message is not None
    assert "699678" in result.message
    assert result.message != "fallback"
    assert any("699678" in str(message.get("content")) for message in seen_messages[1])


def test_ai_agent_validator_wait_same_node_after_agent_allows_missing_edge():
    result = FlowV2GraphValidator().validate(
        nodes=[{"id": "agent", "type": "ai_agent", "data": {"isStart": True, "after_agent_behavior": "wait_same_node"}}],
        edges=[],
    )
    assert result.status == GraphValidationStatus.VALID


def test_ai_agent_mcp_result_text_deterministic_when_final_llm_invalid(monkeypatch):
    calls = iter([
        '{"thought_summary":"calcular","tool":"chamar_mcp","arguments":{"tool_id":"calculate","input":{"expression":"1234 * 567"}}}',
        'not json',
    ])

    def fake_llm(_db, _tenant_id, messages, options=None):
        return next(calls)

    def fake_mcp_executor(tool, args):
        return {"ok": True, "status": "success", "result": {"content": [{"type": "text", "text": "699678"}]}, "latency_ms": 1}

    monkeypatch.setattr(svc, "generate_answer_for_tenant", fake_llm)
    result = svc.run_agent_for_tenant(
        object(),
        uuid.uuid4(),
        "Quanto é 1234 * 567?",
        "Use a ferramenta calculate para cálculos.",
        ["chamar_mcp", "responder"],
        {"mcp_tools": [{"tool_id": "calculate", "name": "calculate", "description": "Calculadora"}]},
        options={"max_steps": 2, "fallback_message": "fallback"},
        mcp_tool_executor=fake_mcp_executor,
    )

    assert result.fallback_used is False
    assert result.message == "O resultado é 699678."
    assert result.message != "fallback"
