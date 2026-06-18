from app.flow_v2.graph_validator import FlowV2GraphValidator, GraphValidationStatus
from app.services.supervisor_service import decide_supervisor_agent


def test_supervisor_decision_selects_valid_agent(monkeypatch):
    monkeypatch.setattr("app.services.supervisor_service.generate_answer_for_tenant", lambda *args, **kwargs: '{"selected_agent":"comercial","reason":"vendas"}')
    decision = decide_supervisor_agent(None, "tenant", message="quero comprar", supervisor_prompt="", agents=[{"id": "comercial", "name": "Comercial", "description": "Vendas"}], context_section="", fallback_agent_id=None)
    assert decision.selected_agent == "comercial"
    assert decision.fallback_used is False


def test_supervisor_decision_invalid_json_uses_fallback(monkeypatch):
    monkeypatch.setattr("app.services.supervisor_service.generate_answer_for_tenant", lambda *args, **kwargs: 'não é json')
    decision = decide_supervisor_agent(None, "tenant", message="boleto", supervisor_prompt="", agents=[{"id": "financeiro", "name": "Financeiro", "description": "Cobrança"}], context_section="", fallback_agent_id="financeiro")
    assert decision.selected_agent == "financeiro"
    assert decision.fallback_used is True
    assert decision.raw_valid is False


def test_supervisor_validator_blocks_empty_and_supervisor_targets():
    validator = FlowV2GraphValidator()
    result = validator.validate(nodes=[{"id": "sup", "type": "ai_supervisor", "data": {"isStart": True, "agent_ids": []}}], edges=[])
    assert result.status == GraphValidationStatus.INVALID
    assert "FLOW_V2_AI_SUPERVISOR_AGENTS_REQUIRED:sup" in result.errors

    result = validator.validate(nodes=[{"id": "sup", "type": "ai_supervisor", "data": {"isStart": True, "agent_ids": ["sup"]}}], edges=[])
    assert result.status == GraphValidationStatus.INVALID
    assert any(error.startswith("FLOW_V2_AI_SUPERVISOR_SELF_TARGET_INVALID:sup") for error in result.errors)


def test_supervisor_validator_accepts_agent_and_fallback():
    result = FlowV2GraphValidator().validate(
        nodes=[
            {"id": "sup", "type": "ai_supervisor", "data": {"isStart": True, "agent_ids": ["agent"], "fallback_agent_id": "agent"}},
            {"id": "agent", "type": "ai_agent", "data": {"allowed_tools": ["responder"]}},
        ],
        edges=[{"source": "sup", "target": "agent"}],
    )
    assert result.status == GraphValidationStatus.VALID
