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


def test_ai_agent_google_calendar_clear_intent_executes_directly_without_llm(monkeypatch):
    from app.services.execution_budget_service import ExecutionBudget
    from app.tools.base import NormalizedToolResult, ToolResult

    registry_calls = []
    budget = ExecutionBudget.defaults("tenant")

    def fail_llm(*args, **kwargs):
        raise AssertionError("LLM should not be called for deterministic calendar create")

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        registry_calls.append({"tool_type": tool_type, "tool_id": tool_id, "input": input})
        if tool_id == "google_calendar_check_availability":
            return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True, "busy": []}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.check_availability", data={}))
        return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True, "title": input["title"]}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.create_event", summary="Evento criado", data=input))

    monkeypatch.setattr(svc, "generate_answer_for_tenant", fail_llm)
    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)
    result = svc.run_agent_for_tenant(
        object(), uuid.uuid4(), "Crie um compromisso amanhã às 14:00 chamado Reunião com Gabriel", "instr",
        ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event", "name": "Criar evento"}]}, options={"max_steps": 2}, budget=budget,
    )
    assert [call["tool_id"] for call in registry_calls] == ["google_calendar_check_availability", "google_calendar_create_event"]
    assert registry_calls[1]["input"]["title"] == "Reunião com Gabriel"
    assert "T14:00:00" in registry_calls[1]["input"]["start"]
    assert result.message.startswith("Pronto! Agendei Reunião com Gabriel para ")
    assert result.message.endswith(" às 14:00.")
    assert result.metadata["budget_llm_calls_used"] == 0
    assert result.metadata["budget_node_tool_calls_used"] == 2
    assert result.metadata["budget_mcp_calls_used"] == 0


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
    assert result.message == f"Não consegui acessar o Google Calendar agora: {msg}"
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



def test_ai_agent_google_calendar_disabled_falls_back_to_normal_flow(monkeypatch):
    calls = []

    def fake_llm(*args, **kwargs):
        calls.append(args)
        return '{"tool":"responder","arguments":{"message":"fluxo normal"}}'

    monkeypatch.setattr(svc, "generate_answer_for_tenant", fake_llm)
    result = svc.run_agent_for_tenant(
        object(), uuid.uuid4(), "Crie um compromisso amanhã às 14:00 chamado Reunião com Gabriel", "instr",
        ["chamar_mcp", "responder"], {"mcp_tools": []}, options={"max_steps": 1},
    )
    assert calls
    assert result.message == "fluxo normal"


def test_ai_agent_google_calendar_missing_time_asks_short_question(monkeypatch):
    def fail_llm(*args, **kwargs):
        raise AssertionError("LLM should not be called when deterministic calendar data is missing")

    monkeypatch.setattr(svc, "generate_answer_for_tenant", fail_llm)
    result = svc.run_agent_for_tenant(
        object(), uuid.uuid4(), "Crie um compromisso amanhã chamado Reunião com Gabriel", "instr",
        ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event"}]}, options={"max_steps": 1},
    )
    assert result.message == "Qual horário você deseja agendar?"


def test_ai_agent_google_calendar_error_returns_reason(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    def fail_llm(*args, **kwargs):
        raise AssertionError("LLM should not be called for deterministic calendar error")

    monkeypatch.setattr(svc, "generate_answer_for_tenant", fail_llm)
    monkeypatch.setattr(svc.ToolRegistry, "execute", lambda self, *a, **k: ToolResult(False, "google_calendar", tool_id="google_calendar_create_event", output={"ok": False, "message": "token_expired"}, error_code="google_calendar_error", normalized_result=NormalizedToolResult(False, "google_calendar_create_event", type="google_calendar.create_event", error={"code": "token_expired"})))
    result = svc.run_agent_for_tenant(
        object(), uuid.uuid4(), "Crie um compromisso amanhã às 14:00 chamado Reunião", "instr",
        ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event"}]}, options={"max_steps": 1},
    )
    assert result.message == "Não consegui acessar o Google Calendar agora: token_expired"


def test_ai_agent_google_calendar_resolves_mcp_display_prefix(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    calls = iter([
        '{"tool":"chamar_mcp","arguments":{"tool_id":"[MCP] google_calendar_create_event","input":{"title":"Reunião com Gabriel"}}}',
        '{"tool":"responder","arguments":{"message":"Evento criado."}}',
    ])
    registry_calls = []

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        registry_calls.append({"tool_type": tool_type, "tool_id": tool_id, "input": input})
        return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.create_event", summary="Evento criado", data=input))

    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: next(calls))
    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)
    result = svc.run_agent_for_tenant(
        object(), uuid.uuid4(), "Crie um compromisso amanhã às 14:00 chamado Reunião com Gabriel", "instr",
        ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event", "name": "[Google Calendar] Criar evento"}]}, options={"max_steps": 2}, budget=None,
    )
    assert registry_calls[0]["tool_type"] == "google_calendar"
    assert registry_calls[0]["tool_id"] == "google_calendar_create_event"
    assert result.fallback_used is False


def test_ai_agent_google_calendar_list_events_executes_directly_without_llm(monkeypatch, caplog):
    from app.services.execution_budget_service import ExecutionBudget
    from app.tools.base import NormalizedToolResult, ToolResult

    registry_calls = []
    budget = ExecutionBudget.defaults("tenant")

    def fail_llm(*args, **kwargs):
        raise AssertionError("LLM should not be called for deterministic calendar list")

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        registry_calls.append({"tool_type": tool_type, "tool_id": tool_id, "input": input})
        return ToolResult(
            True,
            "google_calendar",
            tool_id=tool_id,
            output={"ok": True, "events": [
                {"title": "Reunião com Gabriel", "start": "2026-06-22T14:00:00-03:00"},
                {"title": "Teste Wazza Calendar", "start": "2026-06-22T16:30:00-03:00"},
            ]},
            normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.list_events", summary="ok", data={}),
        )

    monkeypatch.setattr(svc, "generate_answer_for_tenant", fail_llm)
    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)
    with caplog.at_level("INFO"):
        result = svc.run_agent_for_tenant(
            object(), uuid.uuid4(), "Liste meus eventos de amanhã", "instr",
            ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_list_events", "name": "Listar eventos"}]},
            options={"max_steps": 2, "timezone": "America/Sao_Paulo"}, budget=budget,
        )

    assert registry_calls == [{"tool_type": "google_calendar", "tool_id": "google_calendar_list_events", "input": registry_calls[0]["input"]}]
    assert "2026-06-22T00:00:00" in registry_calls[0]["input"]["time_min"]
    assert "2026-06-23T00:00:00" in registry_calls[0]["input"]["time_max"]
    assert result.message == "Você possui 2 compromissos amanhã:\n\n• 14:00 - Reunião com Gabriel\n• 16:30 - Teste Wazza Calendar"
    assert result.metadata["budget_llm_calls_used"] == 0
    assert result.metadata["budget_node_tool_calls_used"] == 1
    assert result.metadata["budget_mcp_calls_used"] == 0
    assert result.metadata["mcp_call_count"] == 0
    assert "AI_AGENT_DETERMINISTIC_CALENDAR_LIST_MATCH" in caplog.text
    assert "AI_AGENT_DETERMINISTIC_CALENDAR_LIST_EXECUTE" in caplog.text
    assert "AI_AGENT_DETERMINISTIC_CALENDAR_LIST_RESULT" in caplog.text


def test_ai_agent_google_calendar_list_events_empty_response(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM should not be called")))
    monkeypatch.setattr(
        svc.ToolRegistry,
        "execute",
        lambda self, tool_type, tool_id, input, context, config=None: ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True, "events": []}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.list_events", summary="ok", data={})),
    )
    result = svc.run_agent_for_tenant(
        object(), uuid.uuid4(), "Quais eventos possuo hoje?", "instr",
        ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_list_events"}]}, options={"max_steps": 1},
    )
    assert result.message == "Você não possui compromissos para hoje."


def test_ai_agent_google_calendar_check_availability_free_without_llm(monkeypatch, caplog):
    from app.services.execution_budget_service import ExecutionBudget
    from app.tools.base import NormalizedToolResult, ToolResult

    registry_calls = []
    budget = ExecutionBudget.defaults("tenant")

    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM should not be called")))

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        registry_calls.append({"tool_type": tool_type, "tool_id": tool_id, "input": input})
        return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True, "busy": []}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.check_availability", summary="ok", data={}))

    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)
    with caplog.at_level("INFO"):
        result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "Tenho horário livre amanhã às 14h?", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_check_availability"}]}, options={"timezone": "America/Sao_Paulo"}, budget=budget)

    assert registry_calls[0]["tool_type"] == "google_calendar"
    assert registry_calls[0]["tool_id"] == "google_calendar_check_availability"
    assert registry_calls[0]["input"]["start"] == "2026-06-22T14:00:00-03:00"
    assert registry_calls[0]["input"]["end"] == "2026-06-22T15:00:00-03:00"
    assert registry_calls[0]["input"]["timezone"] == "America/Sao_Paulo"
    assert result.message == "Sim, você está livre amanhã às 14:00."
    assert result.metadata["budget_llm_calls_used"] == 0
    assert result.metadata["budget_node_tool_calls_used"] == 1
    assert result.metadata["budget_mcp_calls_used"] == 0
    assert "AI_AGENT_DETERMINISTIC_CALENDAR_AVAILABILITY_MATCH" in caplog.text
    assert "AI_AGENT_DETERMINISTIC_CALENDAR_AVAILABILITY_EXECUTE" in caplog.text
    assert "AI_AGENT_DETERMINISTIC_CALENDAR_AVAILABILITY_RESULT" in caplog.text


def test_ai_agent_google_calendar_check_availability_busy_without_llm(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM should not be called")))
    monkeypatch.setattr(
        svc.ToolRegistry,
        "execute",
        lambda self, tool_type, tool_id, input, context, config=None: ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True, "busy": [{"start": input["start"], "end": input["end"], "title": "Reunião com Gabriel"}]}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.check_availability", summary="ok", data={})),
    )
    result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "Estou disponível amanhã às 16:30?", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_check_availability"}]}, options={"timezone": "America/Sao_Paulo"})
    assert result.message == "Não, você já possui compromisso amanhã às 16:30: Reunião com Gabriel."


def test_ai_agent_google_calendar_check_availability_missing_date_without_llm(monkeypatch):
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM should not be called")))
    monkeypatch.setattr(svc.ToolRegistry, "execute", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Tool should not be called")))
    result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "Tenho horário livre às 14h?", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_check_availability"}]})
    assert result.message == "Para qual dia você quer verificar?"


def test_ai_agent_google_calendar_check_availability_missing_time_without_llm(monkeypatch):
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM should not be called")))
    monkeypatch.setattr(svc.ToolRegistry, "execute", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Tool should not be called")))
    result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "Minha agenda está livre amanhã?", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_check_availability"}]})
    assert result.message == "Qual horário você quer verificar?"


def test_ai_agent_google_calendar_create_precheck_free_creates(monkeypatch):
    from app.services.execution_budget_service import ExecutionBudget
    from app.tools.base import NormalizedToolResult, ToolResult

    calls = []
    budget = ExecutionBudget.defaults("tenant")
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM should not be called")))

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        calls.append(tool_id)
        if tool_id == "google_calendar_check_availability":
            return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True, "busy": []}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.check_availability", data={}))
        return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.create_event", summary="Evento criado", data=input))

    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)
    result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "Crie um compromisso amanhã às 09:00 chamado Reunião Online", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event"}]}, options={"timezone": "America/Sao_Paulo"}, budget=budget)
    assert calls == ["google_calendar_check_availability", "google_calendar_create_event"]
    assert result.message.startswith("Pronto! Agendei Reunião Online")
    assert result.metadata["budget_node_tool_calls_used"] == 2
    assert result.metadata["budget_mcp_calls_used"] == 0


def test_ai_agent_google_calendar_create_precheck_busy_sets_pending(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    calls = []
    session_state = {}
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM should not be called")))

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        calls.append(tool_id)
        return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True, "busy": [{"summary": "Reunião Online", "title": "Título ignorado", "start": input["start"], "end": input["end"]}]}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.check_availability", data={}))

    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)
    result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "Crie um compromisso amanhã às 09:00 chamado Call online", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event"}], "session_state": session_state}, options={"timezone": "America/Sao_Paulo"})
    assert calls == ["google_calendar_check_availability"]
    assert result.message == "Você já possui compromisso amanhã às 09:00: Reunião Online. Deseja criar mesmo assim?"
    pending = session_state["pending_google_calendar_create_event"]
    assert pending["summary"] == "Call online"
    assert pending["conflicting_events"][0]["summary"] == "Reunião Online"


def test_ai_agent_google_calendar_create_precheck_busy_uses_title_when_summary_missing(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    session_state = {}
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM should not be called")))

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True, "busy": [{"title": "Reunião Online", "start": input["start"], "end": input["end"]}]}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.check_availability", data={}))

    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)
    result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "Crie um compromisso amanhã às 09:00 chamado Call online", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event"}], "session_state": session_state}, options={"timezone": "America/Sao_Paulo"})
    assert result.message == "Você já possui compromisso amanhã às 09:00: Reunião Online. Deseja criar mesmo assim?"


def test_ai_agent_google_calendar_create_precheck_busy_lists_multiple_events(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    session_state = {}
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM should not be called")))

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True, "busy": [
            {"summary": "Reunião Online", "start": input["start"], "end": input["end"]},
            {"name": "Café", "start": input["start"], "end": input["end"]},
        ]}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.check_availability", data={}))

    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)
    result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "Crie um compromisso amanhã às 09:00 chamado Call online", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event"}], "session_state": session_state}, options={"timezone": "America/Sao_Paulo"})
    assert result.message == "Você já possui estes compromissos nesse horário:\n• Reunião Online\n• Café\nDeseja criar mesmo assim?"


def test_ai_agent_google_calendar_create_precheck_busy_falls_back_to_compromisso_without_name(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    session_state = {}
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM should not be called")))

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True, "busy": [{"start": input["start"], "end": input["end"]}]}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.check_availability", data={}))

    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)
    result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "Crie um compromisso amanhã às 09:00 chamado Call online", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event"}], "session_state": session_state}, options={"timezone": "America/Sao_Paulo"})
    assert result.message == "Você já possui compromisso amanhã às 09:00: compromisso. Deseja criar mesmo assim?"



def test_ai_agent_google_calendar_conflict_confirmation_creates_directly_without_second_prompt(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    session_state = {}
    calls = []
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM should not be called while handling deterministic calendar create or pending confirmation")))

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        calls.append((tool_id, dict(input)))
        if tool_id == "google_calendar_check_availability":
            return ToolResult(
                True,
                "google_calendar",
                tool_id=tool_id,
                output={"ok": True, "busy": [{"title": "Reunião Online", "start": input["start"], "end": input["end"]}]},
                normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.check_availability", data={}),
            )
        assert tool_id == "google_calendar_create_event"
        return ToolResult(
            True,
            "google_calendar",
            tool_id=tool_id,
            output={"ok": True},
            normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.create_event", summary="Evento criado", data=input),
        )

    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)

    first = svc.run_agent_for_tenant(
        object(),
        uuid.uuid4(),
        "Crie um compromisso amanhã às 09:00 chamado Teste",
        "instr",
        ["chamar_mcp", "responder"],
        {"mcp_tools": [{"tool_id": "google_calendar_create_event"}], "session_state": session_state},
        options={"timezone": "America/Sao_Paulo"},
    )
    assert first.message == "Você já possui compromisso amanhã às 09:00: Reunião Online. Deseja criar mesmo assim?"
    assert calls == [("google_calendar_check_availability", calls[0][1])]
    assert "pending_google_calendar_create_event" in session_state

    second = svc.run_agent_for_tenant(
        object(),
        uuid.uuid4(),
        "sim",
        "instr",
        ["chamar_mcp", "responder"],
        {"mcp_tools": [{"tool_id": "google_calendar_create_event"}], "session_state": session_state},
        options={"timezone": "America/Sao_Paulo"},
    )

    assert [call[0] for call in calls] == ["google_calendar_check_availability", "google_calendar_create_event"]
    assert calls[1][1]["summary"] == "Teste"
    assert calls[1][1]["start"] == calls[0][1]["start"]
    assert "pending_google_calendar_create_event" not in session_state
    assert second.message == "Pronto! Agendei Teste para amanhã às 09:00."


def test_ai_agent_google_calendar_pending_confirmation_accepts_ok_and_confirmar(monkeypatch):
    assert svc._calendar_pending_reply_intent("ok") == "confirm"
    assert svc._calendar_pending_reply_intent("confirmar") == "confirm"
    assert svc._calendar_pending_reply_intent("pode criar") == "confirm"
    assert svc._calendar_pending_reply_intent("yes") == "confirm"

def test_ai_agent_google_calendar_pending_yes_creates(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    calls = []
    session_state = {"pending_google_calendar_create_event": {"summary": "Call online", "start_time": "2026-06-22T09:00:00-03:00", "end_time": "2026-06-22T10:00:00-03:00", "timezone": "America/Sao_Paulo", "conflicting_events": [{"title": "Reunião Online"}]}}

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        calls.append((tool_id, input))
        return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.create_event", summary="Evento criado", data=input))

    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)
    result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "sim", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event"}], "session_state": session_state})
    assert calls[0][0] == "google_calendar_create_event"
    assert "pending_google_calendar_create_event" not in session_state
    assert result.message == "Pronto! Agendei Call online para 2026-06-22 às 09:00."


def test_ai_agent_google_calendar_pending_no_cancels(monkeypatch):
    session_state = {"pending_google_calendar_create_event": {"summary": "Call online", "start_time": "2026-06-22T09:00:00-03:00", "end_time": "2026-06-22T10:00:00-03:00", "timezone": "America/Sao_Paulo", "conflicting_events": []}}
    monkeypatch.setattr(svc.ToolRegistry, "execute", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Tool should not be called")))
    result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "não", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event"}], "session_state": session_state})
    assert result.message == "Tudo bem, não criei o compromisso."
    assert "pending_google_calendar_create_event" not in session_state


def test_ai_agent_google_calendar_llm_create_precheck_busy(monkeypatch):
    from app.services.execution_budget_service import ExecutionBudget
    from app.tools.base import NormalizedToolResult, ToolResult

    session_state = {}
    budget = ExecutionBudget.defaults("tenant")
    calls = []
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: '{"tool":"chamar_mcp","arguments":{"tool_id":"google_calendar_create_event","input":{"summary":"Call online","start":"2026-06-22T09:00:00-03:00","end":"2026-06-22T10:00:00-03:00","timezone":"America/Sao_Paulo"}}}')

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        calls.append(tool_id)
        return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True, "busy": [{"title": "Reunião Online", "start": input["start"], "end": input["end"]}]}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.check_availability", data={}))

    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)
    result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "crie evento", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event"}], "session_state": session_state}, options={"max_steps": 1}, budget=budget)
    assert calls == ["google_calendar_check_availability"]
    assert result.message == "Você já possui compromisso amanhã às 09:00: Reunião Online. Deseja criar mesmo assim?"
    assert session_state["pending_google_calendar_create_event"]["summary"] == "Call online"
    assert result.metadata["budget_node_tool_calls_used"] == 1
    assert result.metadata["budget_mcp_calls_used"] == 0
    assert result.metadata["mcp_call_count"] == 0
