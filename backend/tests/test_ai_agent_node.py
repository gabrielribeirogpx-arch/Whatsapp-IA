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


def test_format_deterministic_tool_response_keeps_calculate_numeric_prefix():
    assert svc._format_deterministic_tool_response("calculate", "699678") == "O resultado é 699678."


def test_ai_agent_mcp_get_business_hours_deterministic_natural_without_result_prefix(monkeypatch):
    get_business_hours_id = "70d58c9b-84e0-40fb-994b-ce86a1266d64"
    calls = iter([
        '{"tool_calls":[{"tool":"chamar_mcp","arguments":{"tool_id":"70d58c9b-84e0-40fb-994b-ce86a1266d64","input":{}}}]}',
        '{"thought_summary":"responder","tool":"responder","arguments":{}}',
    ])

    def fake_llm(_db, _tenant_id, messages, options=None):
        return next(calls)

    def fake_mcp_executor(tool, args):
        assert tool["tool_id"] == get_business_hours_id
        assert tool["name"] == "get_business_hours"
        assert args == {}
        return {
            "ok": True,
            "status": "success",
            "result": {"content": [{"type": "text", "text": "Segunda a sexta das 08h às 18h."}]},
            "latency_ms": 1,
        }

    monkeypatch.setattr(svc, "generate_answer_for_tenant", fake_llm)
    result = svc.run_agent_for_tenant(
        object(),
        uuid.uuid4(),
        "Qual é o horário de atendimento?",
        "Use get_business_hours para consultar horário de atendimento.",
        ["chamar_mcp", "responder"],
        {"mcp_tools": [{"tool_id": get_business_hours_id, "name": "get_business_hours", "description": "Horário de atendimento"}]},
        options={"max_steps": 2, "fallback_message": "fallback"},
        mcp_tool_executor=fake_mcp_executor,
    )

    assert result.fallback_used is False
    assert result.message is not None
    assert not result.message.startswith("O resultado é")
    assert "segunda a sexta" in result.message.lower()
    assert "08h às 18h" in result.message


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


def test_ai_agent_mcp_get_business_hours_resolves_tool_id_inside_tool_calls_arguments(monkeypatch):
    get_business_hours_id = "70d58c9b-84e0-40fb-994b-ce86a1266d64"
    calls = iter([
        '{"tool_calls":[{"tool":"chamar_mcp","arguments":{"tool_id":"70d58c9b-84e0-40fb-994b-ce86a1266d64","input":{}}}]}',
        '{"thought_summary":"responder","tool":"responder","arguments":{"message":"Nosso horário de atendimento é de segunda a sexta, das 9h às 18h."}}',
    ])
    registry_calls = []
    original_execute = svc.ToolRegistry.execute

    def fake_llm(_db, _tenant_id, messages, options=None):
        return next(calls)

    def fake_mcp_executor(tool, args):
        assert tool["tool_id"] == get_business_hours_id
        assert tool["name"] == "get_business_hours"
        assert args == {}
        return {
            "ok": True,
            "status": "success",
            "result": {"content": [{"type": "text", "text": "segunda a sexta, das 9h às 18h"}]},
            "latency_ms": 1,
        }

    def spy_execute(self, tool_type, tool_id, input, context, config=None):
        registry_calls.append({"tool_type": tool_type, "tool_id": tool_id, "input": input})
        return original_execute(self, tool_type, tool_id, input, context, config)

    monkeypatch.setattr(svc, "generate_answer_for_tenant", fake_llm)
    monkeypatch.setattr(svc.ToolRegistry, "execute", spy_execute)

    result = svc.run_agent_for_tenant(
        object(),
        uuid.uuid4(),
        "Qual é o horário de atendimento?",
        "Use get_business_hours para consultar horário de atendimento.",
        ["chamar_mcp", "responder"],
        {"mcp_tools": [{"tool_id": get_business_hours_id, "name": "get_business_hours", "description": "Horário de atendimento"}]},
        options={"max_steps": 2, "fallback_message": "fallback"},
        mcp_tool_executor=fake_mcp_executor,
    )

    assert registry_calls == [{"tool_type": "mcp_tool", "tool_id": get_business_hours_id, "input": {}}]
    assert result.fallback_used is False
    assert result.message == "Nosso horário de atendimento é de segunda a sexta, das 9h às 18h."
    assert result.message != "fallback"
    assert result.metadata["mcp_tools_used"][0]["tool_id"] == get_business_hours_id


def test_ai_agent_mcp_get_business_hours_uses_responder_arguments_text(monkeypatch):
    get_business_hours_id = "70d58c9b-84e0-40fb-994b-ce86a1266d64"
    calls = iter([
        '{"tool_calls":[{"tool":"chamar_mcp","arguments":{"tool_id":"70d58c9b-84e0-40fb-994b-ce86a1266d64","input":{}}}]}',
        '{"thought_summary":"responder","tool":"responder","arguments":{"text":"Nosso horário de atendimento é de segunda a sexta, das 08h às 18h."}}',
    ])

    def fake_llm(_db, _tenant_id, messages, options=None):
        return next(calls)

    def fake_mcp_executor(tool, args):
        assert tool["tool_id"] == get_business_hours_id
        assert args == {}
        return {
            "ok": True,
            "status": "success",
            "result": {"content": [{"type": "text", "text": "Segunda a sexta das 08h às 18h."}]},
            "latency_ms": 1,
        }

    monkeypatch.setattr(svc, "generate_answer_for_tenant", fake_llm)
    result = svc.run_agent_for_tenant(
        object(),
        uuid.uuid4(),
        "Qual é o horário de atendimento?",
        "Use get_business_hours para consultar horário de atendimento.",
        ["chamar_mcp", "responder"],
        {"mcp_tools": [{"tool_id": get_business_hours_id, "name": "get_business_hours", "description": "Horário de atendimento"}]},
        options={"max_steps": 2, "fallback_message": "fallback"},
        mcp_tool_executor=fake_mcp_executor,
    )

    assert result.fallback_used is False
    assert result.message is not None
    assert "segunda a sexta" in result.message.lower()
    assert result.message == "Nosso horário de atendimento é de segunda a sexta, das 08h às 18h."
    assert result.message != "fallback"


def test_ai_agent_mcp_calendar_structured_result_in_context_and_final_response(monkeypatch):
    calls = iter([
        '{"thought_summary":"agendar","tool":"chamar_mcp","arguments":{"tool_id":"calendar_create_event","input":{"title":"Reunião com João"}}}',
        '{"thought_summary":"responder","tool":"responder","arguments":{"message":"Perfeito! Agendei Reunião com João para amanhã às 14:00."}}',
    ])
    seen_messages = []

    def fake_llm(_db, _tenant_id, messages, options=None):
        seen_messages.append(messages)
        return next(calls)

    def fake_mcp_executor(tool, args):
        return {
            "ok": True,
            "status": "success",
            "result": {
                "content": [{"type": "text", "text": "Evento criado: Reunião com João em amanhã às 14:00 por 60 minutos."}],
                "structuredContent": {
                    "ok": True,
                    "tool": "calendar_create_event",
                    "result": {
                        "event_id": "evt_123",
                        "title": "Reunião com João",
                        "date": "amanhã",
                        "time": "14:00",
                        "duration_minutes": 60,
                        "attendees": [],
                        "description": "",
                    },
                },
            },
            "latency_ms": 1,
        }

    monkeypatch.setattr(svc, "generate_answer_for_tenant", fake_llm)
    result = svc.run_agent_for_tenant(
        object(),
        uuid.uuid4(),
        "Agende reunião com João amanhã às 14h",
        "Use calendar_create_event para criar eventos.",
        ["chamar_mcp", "responder"],
        {"mcp_tools": [{"tool_id": "calendar_create_event", "name": "calendar_create_event", "description": "Agenda"}]},
        options={"max_steps": 2, "fallback_message": "fallback"},
        mcp_tool_executor=fake_mcp_executor,
    )

    assert result.fallback_used is False
    assert result.message == "Perfeito! Agendei Reunião com João para amanhã às 14:00."
    final_context = str(seen_messages[1])
    assert "Tool result:" in final_context
    assert "tool=calendar_create_event" in final_context
    assert "structured_result" in final_context
    assert "Reunião com João" in final_context
    assert "14:00" in final_context


def test_ai_agent_mcp_calendar_structured_result_deterministic_when_final_llm_invalid(monkeypatch):
    calls = iter([
        '{"thought_summary":"agendar","tool":"chamar_mcp","arguments":{"tool_id":"calendar_create_event","input":{}}}',
        'not json',
    ])

    def fake_llm(_db, _tenant_id, messages, options=None):
        return next(calls)

    def fake_mcp_executor(tool, args):
        return {
            "ok": True,
            "status": "success",
            "result": {
                "content": [{"type": "text", "text": "Evento criado."}],
                "structuredContent": {"ok": True, "tool": "calendar_create_event", "result": {"title": "Reunião com João", "date": "amanhã", "time": "14:00"}},
            },
        }

    monkeypatch.setattr(svc, "generate_answer_for_tenant", fake_llm)
    result = svc.run_agent_for_tenant(
        object(), uuid.uuid4(), "agendar", "instr", ["chamar_mcp", "responder"],
        {"mcp_tools": [{"tool_id": "calendar_create_event", "name": "calendar_create_event"}]},
        options={"max_steps": 2, "fallback_message": "fallback"}, mcp_tool_executor=fake_mcp_executor,
    )

    assert result.fallback_used is False
    assert result.message == "Perfeito! Agendei Reunião com João para amanhã às 14:00."


def test_ai_agent_mcp_structured_ok_false_not_success(monkeypatch):
    calls = iter([
        '{"thought_summary":"agendar","tool":"chamar_mcp","arguments":{"tool_id":"calendar_create_event","input":{}}}',
        '{"thought_summary":"responder","tool":"responder","arguments":{}}',
    ])

    def fake_llm(_db, _tenant_id, messages, options=None):
        return next(calls)

    def fake_mcp_executor(tool, args):
        return {
            "ok": True,
            "status": "success",
            "result": {
                "content": [{"type": "text", "text": "Não consegui criar o evento."}],
                "structuredContent": {"ok": False, "tool": "calendar_create_event", "error": "calendar_conflict"},
            },
        }

    monkeypatch.setattr(svc, "generate_answer_for_tenant", fake_llm)
    result = svc.run_agent_for_tenant(
        object(), uuid.uuid4(), "agendar", "instr", ["chamar_mcp", "responder"],
        {"mcp_tools": [{"tool_id": "calendar_create_event", "name": "calendar_create_event"}]},
        options={"max_steps": 2, "fallback_message": "fallback"}, mcp_tool_executor=fake_mcp_executor,
    )

    assert result.fallback_used is True
    assert result.message == "fallback"
    assert result.metadata["mcp_status"] == "error"
    assert result.metadata["mcp_error_sanitized"] == "calendar_conflict"


def test_ai_agent_google_calendar_create_event_is_sent_to_llm_payload(monkeypatch, caplog):
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: '{"tool":"responder","arguments":{"message":"ok"}}')
    with caplog.at_level("INFO"):
        svc.run_agent_for_tenant(
            object(), uuid.uuid4(), "oi", "instr", ["chamar_mcp", "responder"],
            {"mcp_tools": [{"tool_id": "google_calendar_create_event", "name": "Criar evento", "metadata": {"provider": "google_calendar"}}]},
            options={"max_steps": 1, "node_id": "agent-1", "selected_tool_ids": ["google_calendar_create_event"]},
        )
    assert "AI_AGENT_NODE_ALLOWED_TOOLS" in caplog.text
    assert "google_calendar_create_event" in caplog.text
    assert "AI_AGENT_LLM_TOOLS_PAYLOAD" in caplog.text
    assert "internal/google_calendar" in caplog.text


def test_ai_agent_tool_call_google_calendar_create_event_routes_to_real_adapter(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    calls = iter([
        '{"tool":"chamar_mcp","arguments":{"tool_id":"google_calendar_create_event","input":{"title":"Reunião com Gabriel","start":"2026-06-21T14:00:00-03:00"}}}',
        '{"tool":"responder","arguments":{"message":"Evento criado."}}',
    ])
    registry_calls = []
    original_execute = svc.ToolRegistry.execute

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        registry_calls.append({"tool_type": tool_type, "tool_id": tool_id, "input": input})
        if tool_type == "google_calendar":
            return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True, "title": input["title"]}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.create_event", summary="Evento criado", data={"title": input["title"]}))
        return original_execute(self, tool_type, tool_id, input, context, config)

    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: next(calls))
    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)
    result = svc.run_agent_for_tenant(
        object(), uuid.uuid4(), "Crie um compromisso amanhã às 14:00 chamado Reunião com Gabriel", "instr",
        ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event", "name": "Criar evento"}]}, options={"max_steps": 2}, budget=None,
    )
    assert registry_calls[0]["tool_type"] == "google_calendar"
    assert registry_calls[0]["tool_id"] == "google_calendar_create_event"
    assert result.message == "Evento criado."


def test_ai_agent_google_calendar_deterministic_fallback_when_llm_does_not_call_tool(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: '{"tool":"responder","arguments":{}}')

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        assert tool_type == "google_calendar"
        assert tool_id == "google_calendar_create_event"
        assert input["title"] == "Reunião com Gabriel"
        return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.create_event", summary="Evento Reunião com Gabriel criado", data=input))

    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)
    result = svc.run_agent_for_tenant(
        object(), uuid.uuid4(), "Crie um compromisso amanhã às 14:00 chamado Reunião com Gabriel", "instr",
        ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event", "name": "Criar evento"}]}, options={"max_steps": 1, "fallback_message": "fallback"},
    )
    assert result.fallback_used is False
    assert "Reunião com Gabriel" in result.message


def test_ai_agent_google_calendar_not_connected_returns_friendly_message(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: '{"tool":"responder","arguments":{}}')
    msg = "Google Calendar não está conectado para este workspace."
    monkeypatch.setattr(svc.ToolRegistry, "execute", lambda self, *a, **k: ToolResult(False, "google_calendar", tool_id="google_calendar_create_event", output={"ok": False, "message": msg}, error_code="google_calendar_error", normalized_result=NormalizedToolResult(False, "google_calendar_create_event", type="google_calendar.create_event", error={"code": msg})))
    result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "Crie um compromisso amanhã às 14:00 chamado Reunião", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event"}]}, options={"max_steps": 1, "fallback_message": "fallback"})
    assert result.message == msg
    assert result.message != "fallback"


def test_ai_agent_google_calendar_logs_and_budget_increment(monkeypatch, caplog):
    from app.services.execution_budget_service import ExecutionBudget
    from app.tools.base import NormalizedToolResult, ToolResult

    calls = iter(['{"tool":"chamar_mcp","arguments":{"tool_id":"google_calendar_create_event","input":{"title":"X"}}}', '{"tool":"responder","arguments":{"message":"ok"}}'])
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: next(calls))
    monkeypatch.setattr(svc.ToolRegistry, "execute", lambda self, *a, **k: ToolResult(True, "google_calendar", tool_id="google_calendar_create_event", output={"ok": True}, normalized_result=NormalizedToolResult(True, "google_calendar_create_event", type="google_calendar.create_event", summary="ok", data={})))
    budget = ExecutionBudget.defaults("tenant")
    with caplog.at_level("INFO"):
        result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "crie evento", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event"}]}, options={"max_steps": 2}, budget=budget)
    assert "AI_AGENT_TOOL_CALL_REQUESTED" in caplog.text
    assert "AI_AGENT_TOOL_CALL_ROUTED" in caplog.text
    assert "AI_AGENT_TOOL_CALL_RESULT" in caplog.text
    assert result.metadata["budget_node_tool_calls_used"] == 1
    assert result.metadata["budget_mcp_calls_used"] == 0
