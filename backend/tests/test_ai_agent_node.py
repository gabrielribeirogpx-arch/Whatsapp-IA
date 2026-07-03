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
        data = {**input, "ok": True, "event_id": "evt_123", "html_link": "https://calendar.google.com/event?eid=evt_123"}
        return ToolResult(True, "google_calendar", tool_id=tool_id, output=data, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.create_event", summary="Evento criado", data=data))

    monkeypatch.setattr(svc, "generate_answer_for_tenant", fail_llm)
    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)
    result = svc.run_agent_for_tenant(
        object(), uuid.uuid4(), "Crie um compromisso amanhã às 14:00 chamado Reunião com Gabriel", "instr",
        ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event", "name": "Criar evento"}]}, options={"max_steps": 2}, budget=budget,
    )
    assert [call["tool_id"] for call in registry_calls] == ["google_calendar_check_availability", "google_calendar_create_event"]
    assert registry_calls[1]["input"]["title"] == "Reunião com Gabriel"
    assert "T14:00:00" in registry_calls[1]["input"]["start"]
    assert result.message.startswith("✅ Reunião com Gabriel criado!\n📅 ")
    assert "14:00" in result.message
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
        data = {**input, "ok": True, "event_id": "evt_456", "htmlLink": "https://calendar.google.com/event?eid=evt_456"}
        return ToolResult(True, "google_calendar", tool_id=tool_id, output=data, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.create_event", summary="Evento Reunião com Gabriel criado", data=data))

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
    assert result.message == "⚠️ Não consegui acessar seu Google Calendar. Conecte sua conta Google novamente."
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
    assert result.message == "⚠️ Não consegui acessar seu Google Calendar. Conecte sua conta Google novamente."


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
    assert result.message == 'Você já possui um compromisso amanhã às 09:00:\n\n• Reunião Online\n\nDeseja criar "Call online" mesmo assim?'
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
    assert result.message == 'Você já possui um compromisso amanhã às 09:00:\n\n• Reunião Online\n\nDeseja criar "Call online" mesmo assim?'


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
    assert result.message == 'Já existem 2 compromissos amanhã às 09:00:\n\n• Reunião Online\n• Café\n\nDeseja criar "Call online" mesmo assim?'


def test_ai_agent_google_calendar_create_precheck_busy_falls_back_to_compromisso_without_name(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    session_state = {}
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: (_ for _ in ()).throw(AssertionError("LLM should not be called")))

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True, "busy": [{"start": input["start"], "end": input["end"]}]}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.check_availability", data={}))

    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)
    result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "Crie um compromisso amanhã às 09:00 chamado Call online", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event"}], "session_state": session_state}, options={"timezone": "America/Sao_Paulo"})
    assert result.message == 'Você já possui um compromisso amanhã às 09:00:\n\n• compromisso\n\nDeseja criar "Call online" mesmo assim?'



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
    assert first.message == 'Você já possui um compromisso amanhã às 09:00:\n\n• Reunião Online\n\nDeseja criar "Teste" mesmo assim?'
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
    assert calls[1][1]["ignore_conflicts"] is True
    assert calls[1][1]["force_create"] is True
    assert "pending_google_calendar_create_event" not in session_state
    assert second.message == "Pronto! Agendei Teste para amanhã às 09:00."


def test_ai_agent_google_calendar_pending_confirmation_accepts_ok_and_confirmar(monkeypatch):
    from app.services.pending_action_service import detect_pending_action_decision
    assert detect_pending_action_decision("ok") == "confirm"
    assert detect_pending_action_decision("confirmar") == "confirm"
    assert detect_pending_action_decision("pode criar") == "confirm"
    assert detect_pending_action_decision("yes") == "confirm"

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
    assert calls[0][1]["ignore_conflicts"] is True
    assert calls[0][1]["force_create"] is True
    assert "pending_google_calendar_create_event" not in session_state
    assert result.message == "Pronto! Agendei Call online para 2026-06-22 às 09:00."


def test_ai_agent_google_calendar_pending_time_update_reuses_previous_args(monkeypatch, caplog):
    from app.tools.base import NormalizedToolResult, ToolResult

    calls = []
    session_state = {
        "pending_google_calendar_create_event": {
            "summary": "Call online",
            "start_time": "2026-06-22T09:00:00-03:00",
            "end_time": "2026-06-22T10:00:00-03:00",
            "timezone": "America/Sao_Paulo",
            "conflicting_events": [{"title": "Reunião Online"}],
        }
    }

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        calls.append((tool_id, dict(input)))
        if tool_id == "google_calendar_check_availability":
            return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True, "busy": []}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.check_availability", data={}))
        return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.create_event", summary="Evento criado", data=input))

    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)

    with caplog.at_level("INFO"):
        result = svc.run_agent_for_tenant(
            object(),
            uuid.uuid4(),
            "Marque para 15:30",
            "instr",
            ["chamar_mcp", "responder"],
            {"mcp_tools": [{"tool_id": "google_calendar_create_event"}], "session_state": session_state},
            memory_context="user: Crie um compromisso amanhã às 09:00 chamado Call online\nassistant: horário ocupado",
            options={"timezone": "America/Sao_Paulo"},
        )

    assert [call[0] for call in calls] == ["google_calendar_check_availability", "google_calendar_create_event"]
    assert calls[1][1]["summary"] == "Call online"
    assert calls[1][1]["start"] == "2026-06-22T15:30:00-03:00"
    assert calls[1][1]["end"] == "2026-06-22T16:30:00-03:00"
    assert "pending_google_calendar_create_event" not in session_state
    assert "AI_SYSTEM_TOOL_INPUT" in caplog.text
    assert "horário ocupado" in caplog.text
    assert result.message == "Pronto! Agendei Call online para 2026-06-22 às 15:30."


def test_ai_agent_google_calendar_pending_no_cancels(monkeypatch):
    session_state = {"pending_google_calendar_create_event": {"summary": "Call online", "start_time": "2026-06-22T09:00:00-03:00", "end_time": "2026-06-22T10:00:00-03:00", "timezone": "America/Sao_Paulo", "conflicting_events": []}}
    monkeypatch.setattr(svc.ToolRegistry, "execute", lambda *a, **k: (_ for _ in ()).throw(AssertionError("Tool should not be called")))
    result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "não", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event"}], "session_state": session_state})
    assert result.message == "Tudo bem, operação cancelada."
    assert "pending_google_calendar_create_event" not in session_state


def test_ai_agent_google_calendar_after_pending_cancel_new_messages_follow_normal_flow(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    session_state = {"pending_google_calendar_create_event": {"summary": "Call online", "start": "2026-06-22T09:00:00-03:00", "end": "2026-06-22T10:00:00-03:00", "timezone": "America/Sao_Paulo", "conflicting_events": []}}
    calls = []

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        calls.append(tool_id)
        if tool_id == "google_calendar_check_availability":
            return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True, "busy": []}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.check_availability", data={}))
        return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.create_event", summary="Evento criado", data=input))

    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)
    cancelled = svc.run_agent_for_tenant(object(), uuid.uuid4(), "não", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event"}], "session_state": session_state}, options={"timezone": "America/Sao_Paulo"})
    assert cancelled.message == "Tudo bem, operação cancelada."
    assert "pending_google_calendar_create_event" not in session_state

    created = svc.run_agent_for_tenant(object(), uuid.uuid4(), "Crie um compromisso amanhã às 09:00 chamado Novo", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event"}], "session_state": session_state}, options={"timezone": "America/Sao_Paulo"})
    assert calls == ["google_calendar_check_availability", "google_calendar_create_event"]
    assert created.message.startswith("Pronto! Agendei Novo")


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
    assert result.message == 'Você já possui um compromisso amanhã às 09:00:\n\n• Reunião Online\n\nDeseja criar "Call online" mesmo assim?'
    assert session_state["pending_google_calendar_create_event"]["summary"] == "Call online"
    assert result.metadata["budget_node_tool_calls_used"] == 1
    assert result.metadata["budget_mcp_calls_used"] == 0
    assert result.metadata["mcp_call_count"] == 0


def test_ai_agent_generic_pending_action_confirm_creates_directly_without_rechecking(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    pending_payload = {"summary": "Call online", "start_time": "2026-06-22T09:00:00-03:00", "end_time": "2026-06-22T10:00:00-03:00", "timezone": "America/Sao_Paulo", "conflicting_events": [{"title": "Reunião"}]}

    class Pending:
        id = uuid.uuid4()
        action_type = svc.CALENDAR_CREATE_CONFIRMATION
        payload_json = pending_payload

    consumed = []

    class FakePendingActionService:
        def __init__(self, db):
            pass

        def get_pending_action(self, **kwargs):
            return Pending()

        def consume_pending_action(self, **kwargs):
            consumed.append(kwargs)
            return True

        def cancel_pending_action(self, **kwargs):
            raise AssertionError("should not cancel")

    calls = []

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        calls.append(tool_id)
        assert tool_id == "google_calendar_create_event"
        assert input["ignore_conflicts"] is True
        assert input["force_create"] is True
        return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.create_event", summary="Evento criado", data=input))

    monkeypatch.setattr(svc, "PendingActionService", FakePendingActionService)
    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)
    result = svc.run_agent_for_tenant(object(), tenant_id, "sim", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event"}], "memory_context": {"conversation_id": conversation_id}}, options={})
    assert result.status == "success"
    assert calls == ["google_calendar_create_event"]
    assert consumed


def test_ai_agent_generic_pending_action_cancel_clears_without_tool_call(monkeypatch):
    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()

    class Pending:
        id = uuid.uuid4()
        action_type = svc.CALENDAR_CREATE_CONFIRMATION
        payload_json = {"summary": "Call", "start_time": "2026-06-22T09:00:00-03:00", "end_time": "2026-06-22T10:00:00-03:00"}

    cancelled = []

    class FakePendingActionService:
        def __init__(self, db):
            pass

        def get_pending_action(self, **kwargs):
            return Pending()

        def consume_pending_action(self, **kwargs):
            raise AssertionError("should not consume")

        def cancel_pending_action(self, **kwargs):
            cancelled.append(kwargs)
            return True

    monkeypatch.setattr(svc, "PendingActionService", FakePendingActionService)
    monkeypatch.setattr(svc.ToolRegistry, "execute", lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not call tools")))
    result = svc.run_agent_for_tenant(object(), tenant_id, "não", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event"}], "memory_context": {"conversation_id": conversation_id}}, options={})
    assert result.message == "Tudo bem, operação cancelada."
    assert cancelled


def test_format_tool_result_gmail_messages_use_data_and_hide_internal_ids():
    normalized = {
        "ok": True,
        "tool": "gmail_list_messages",
        "type": "gmail.list_messages",
        "summary": "Operação do Gmail concluída",
        "data": {"messages": [
            {"message_id": "m1", "thread_id": "t1", "raw": "secret", "subject": "Security alert", "from": "Google <no-reply@accounts.google.com>", "date": "2026-06-21T10:30:00-03:00", "snippet": "Novo login detectado."},
            {"id": "m2", "thread_id": "t2", "token": "abc", "subject": "Deployment crashed", "from": "Railway <hello@notify.railway.app>", "date": "2026-06-21T09:00:00-03:00", "snippet": "O deploy falhou."},
        ]},
    }

    response = svc.format_tool_result_for_user("gmail_list_messages", normalized)

    assert "Encontrei seus 2 últimos e-mails" in response
    assert "Security alert" in response
    assert "Google <no-reply@accounts.google.com>" in response
    assert "Deployment crashed" in response
    assert "message_id" not in response
    assert "thread_id" not in response
    assert "raw" not in response
    assert "token" not in response
    assert response != "Perfeito! Operação do Gmail concluída."


def test_format_tool_result_gmail_empty_messages():
    response = svc.format_tool_result_for_user("gmail_list_messages", {"ok": True, "data": {"messages": []}, "summary": "ok"})
    assert response == "Não encontrei e-mails recentes."


def test_format_tool_result_calendar_events():
    response = svc.format_tool_result_for_user("google_calendar_list_events", {"ok": True, "data": {"events": [
        {"title": "Reunião", "start": "2026-06-22T14:00:00-03:00"},
        {"summary": "Café", "start": {"dateTime": "2026-06-22T16:30:00-03:00"}},
    ]}})
    assert "Encontrei 2 eventos" in response
    assert "22/06/2026 14:00 - Reunião" in response
    assert "22/06/2026 16:30 - Café" in response


def test_format_tool_result_result_text_before_summary():
    response = svc.format_tool_result_for_user("calculate", {"ok": True, "summary": "Operação concluída", "result_text": "O resultado é 42."})
    assert response == "O resultado é 42."


def test_format_tool_result_summary_when_no_useful_data():
    response = svc.format_tool_result_for_user("generic", {"ok": True, "summary": "Operação concluída"})
    assert response == "Operação concluída."


def test_ai_agent_final_response_not_generic_gmail_summary_when_messages_exist(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    calls = iter([
        '{"thought_summary":"listar","tool":"chamar_mcp","arguments":{"tool_id":"gmail_list_messages","input":{"max_results":2}}}',
        '{"thought_summary":"responder","tool":"responder","arguments":{}}',
    ])

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        output = {"messages": [{"message_id": "m1", "thread_id": "t1", "subject": "Security alert", "from": "Google <no-reply@accounts.google.com>", "date": "2026-06-21T10:30:00-03:00", "snippet": "Novo login detectado."}]}
        return ToolResult(True, "gmail", tool_id=tool_id, output=output, normalized_result=NormalizedToolResult(True, tool_id, type="gmail.list_messages", summary="Operação do Gmail concluída", data=output))

    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: next(calls))
    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)

    result = svc.run_agent_for_tenant(
        object(), uuid.uuid4(), "Liste meus últimos 2 e-mails", "instr",
        ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "gmail_list_messages", "name": "Listar e-mails"}]}, options={"max_steps": 2},
    )

    assert "Security alert" in (result.message or "")
    assert "Operação do Gmail concluída" not in (result.message or "")
    assert "message_id" not in (result.message or "")
    assert "thread_id" not in (result.message or "")


def test_ai_agent_mutating_google_drive_create_folder_finalizes_without_second_llm(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    llm_calls = []
    execute_calls = []

    def fake_llm(*args, **kwargs):
        llm_calls.append(args)
        return '{"tool":"chamar_mcp","arguments":{"tool_id":"google_drive_create_folder","input":{"name":"Teste Google Drive"}}}'

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        execute_calls.append((tool_type, tool_id, input))
        output = {"ok": True, "existing": False, "folder": {"name": input["name"], "file_id": "folder-1"}}
        return ToolResult(True, "google_drive", tool_id=tool_id, output=output, normalized_result=NormalizedToolResult(True, tool_id, type="google_drive.create_folder", data=output))

    monkeypatch.setattr(svc, "generate_answer_for_tenant", fake_llm)
    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)

    result = svc.run_agent_for_tenant(
        object(), uuid.uuid4(), "Crie uma pasta chamado Teste Google Drive", "instr",
        ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_drive_create_folder", "name": "Criar pasta"}]}, options={"max_steps": 3},
    )

    assert len(llm_calls) == 1
    assert execute_calls == [("google_drive", "google_drive_create_folder", {"name": "Teste Google Drive"})]
    assert result.message == "Pasta criada no Google Drive: Teste Google Drive."


def test_ai_agent_duplicate_mutating_tool_fingerprint_blocks_repeat(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    execute_calls = []
    fingerprint = svc._tool_fingerprint("google_drive_create_folder", {"name": "Teste Google Drive"})

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        execute_calls.append(tool_id)
        output = {"ok": True, "folder": {"name": input["name"]}}
        return ToolResult(True, "google_drive", tool_id=tool_id, output=output, normalized_result=NormalizedToolResult(True, tool_id, type="google_drive.create_folder", data=output))

    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: '{"tool":"chamar_mcp","arguments":{"tool_id":"google_drive_create_folder","input":{"name":"Teste Google Drive"}}}')
    monkeypatch.setattr(svc, "_is_mutating_tool", lambda tool_id: False)
    monkeypatch.setattr(svc, "_tool_fingerprint", lambda tool_id, tool_input: fingerprint)

    result = svc.run_agent_for_tenant(
        object(), uuid.uuid4(), "repita", "instr", ["chamar_mcp", "responder"],
        {"mcp_tools": [{"tool_id": "google_drive_create_folder", "name": "Criar pasta"}]}, options={"max_steps": 2},
    )

    assert execute_calls == ["google_drive_create_folder"]
    assert result.metadata["blocked_tool_calls"] == [{"tool_id": "google_drive_create_folder", "error": "duplicate_tool_call_blocked"}]


def test_ai_agent_read_only_google_drive_list_files_can_iterate(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    calls = iter([
        '{"tool":"chamar_mcp","arguments":{"tool_id":"google_drive_list_files","input":{"max_results":1}}}',
        '{"tool":"responder","arguments":{"message":"Listei os arquivos."}}',
    ])
    execute_calls = []

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        execute_calls.append(tool_id)
        output = {"ok": True, "files": []}
        return ToolResult(True, "google_drive", tool_id=tool_id, output=output, normalized_result=NormalizedToolResult(True, tool_id, type="google_drive.list_files", data=output))

    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: next(calls))
    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)

    result = svc.run_agent_for_tenant(
        object(), uuid.uuid4(), "liste", "instr", ["chamar_mcp", "responder"],
        {"mcp_tools": [{"tool_id": "google_drive_list_files", "name": "Listar"}]}, options={"max_steps": 2},
    )

    assert execute_calls == ["google_drive_list_files"]
    assert result.message == "Listei os arquivos."


def test_ai_agent_google_calendar_create_event_without_event_id_is_incomplete(monkeypatch):
    from app.tools.base import NormalizedToolResult, ToolResult

    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: '{"tool":"chamar_mcp","arguments":{"tool_id":"google_calendar_create_event","input":{"title":"Reunião","start":"2026-06-25T14:00:00-03:00","end":"2026-06-25T15:00:00-03:00"}}}')

    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        return ToolResult(True, "google_calendar", tool_id=tool_id, output={"ok": True, "title": "Reunião", "start": input.get("start"), "end": input.get("end")}, normalized_result=NormalizedToolResult(True, tool_id, type="google_calendar.create_event", summary="Operação do Google Calendar concluída", data={"ok": True, "title": "Reunião", "start": input.get("start"), "end": input.get("end")}))

    monkeypatch.setattr(svc.ToolRegistry, "execute", fake_execute)
    result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "agende", "instr", ["chamar_mcp", "responder"], {"mcp_tools": [{"tool_id": "google_calendar_create_event"}]}, options={"max_steps": 1, "fallback_message": "fallback"})
    assert result.message == "⚠️ Tentei criar o evento, mas não recebi confirmação do Google Calendar. Pode tentar novamente?"
    assert "Operação do Google Calendar concluída" not in result.message


def test_ai_agent_final_response_extracts_nested_responder_text(monkeypatch):
    import json

    nested = json.dumps({"tool_results": [{"tool": "responder", "arguments": {"text": "✅ Reunião criada!\n📅 Amanhã, 14h\n📝 Reunião de Negócios com Vitor"}}]}, ensure_ascii=False)
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: nested)
    result = svc.run_agent_for_tenant(object(), uuid.uuid4(), "oi", "instr", ["responder"], {}, options={"max_steps": 1, "fallback_message": "fallback"})
    assert result.message == "✅ Reunião criada!\n📅 Amanhã, 14h\n📝 Reunião de Negócios com Vitor"
    assert result.fallback_used is False


def test_calendar_formatter_accepts_google_calendar_variations():
    msg = svc.format_tool_result_for_user("google_calendar_create_event", {
        "ok": True,
        "type": "google_calendar.create_event",
        "summary": "Operação do Google Calendar concluída",
        "data": {"id": "evt_789", "summary": "Reunião de Negócios com Vitor", "htmlLink": "https://calendar.google.com", "start": {"dateTime": "2026-06-25T14:00:00-03:00"}, "end": {"dateTime": "2026-06-25T15:00:00-03:00"}},
    })
    assert "Operação do Google Calendar concluída" not in msg
    assert "Reunião de Negócios com Vitor" in msg
    assert "14:00" in msg
