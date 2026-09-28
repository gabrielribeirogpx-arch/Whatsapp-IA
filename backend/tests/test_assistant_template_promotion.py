from copy import deepcopy
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.routers.marketplace import AssistantTemplateMapping, PromoteTemplateBody
from app.services.official_marketplace_template_service import _assistant_contract


def graph():
    ids = {name: uuid4() for name in ("clinic", "services", "availability", "create", "handoff", "other")}
    nodes = [
        {"id": str(ids["clinic"]), "type": "message", "data": {"label": "Boas-vindas", "content": "Olá! 👋 Você está falando com a {{clinic_name}}. Como posso ajudar?"}},
        {"id": str(ids["services"]), "type": "choice", "data": {"options_mode": "fixed", "options": [{"id": "old", "value": "old"}], "result_variable": "selected_service"}},
        {"id": str(ids["availability"]), "type": "mcp_tool", "data": {"connection_id": f"integration:{uuid4()}", "tool_name": "google_calendar_check_availability", "arguments": {"unchanged": True}, "output_variable": "availability"}},
        {"id": str(ids["create"]), "type": "mcp_tool", "data": {"connection_id": f"integration:{uuid4()}", "tool_name": "google_calendar_create_event", "arguments": {"unchanged": True}, "output_variable": "created"}},
        {"id": str(ids["handoff"]), "type": "action", "data": {"action_type": "transfer_human", "reason": "original", "params": {"reason": "original"}}},
        {"id": str(ids["other"]), "type": "message", "data": {"content": "untouched"}},
    ]
    mapping = AssistantTemplateMapping(
        clinic_name_node_id=ids["clinic"], clinic_name_field="data.content",
        services_node_id=ids["services"],
        calendar_node_ids=[ids["availability"], ids["create"]],
        handoff_node_ids=[ids["handoff"]],
    )
    return nodes, ids, mapping


def test_explicit_mapping_builds_canonical_contract_and_sanitizes_connections():
    nodes, ids, mapping = graph()
    original = deepcopy(nodes)
    promoted, contract = _assistant_contract(deepcopy(nodes), mapping)

    assert contract["schema_version"] == 1
    assert contract["service_selection_variable"] == "selected_service"
    assert [target["parameter"] for target in contract["targets"]] == [
        "clinic_name", "services", "google_calendar_connection_id",
        "google_calendar_connection_id", "handoff.reason",
    ]
    assert contract["targets"][0]["operation"] == "interpolate"
    keys = [node["data"].get("template_node_key") for node in promoted if node["data"].get("template_node_key")]
    assert len(keys) == len(set(keys)) == 5
    calendars = [node for node in promoted if node["id"] in {str(ids["availability"]), str(ids["create"])}]
    assert all(node["data"]["connection_id"] == "{{integration.connection}}" for node in calendars)
    assert [node["data"]["tool_name"] for node in calendars] == [node["data"]["tool_name"] for node in original[2:4]]
    assert [node["data"]["arguments"] for node in calendars] == [node["data"]["arguments"] for node in original[2:4]]
    assert promoted[-1] == original[-1]
    assert nodes == original


@pytest.mark.parametrize("change,error", [
    (lambda m: setattr(m, "calendar_node_ids", []), "assistant_calendar_mapping_required"),
    (lambda m: setattr(m, "services_node_id", m.clinic_name_node_id), "node_roles_must_be_unique"),
])
def test_invalid_mapping_fails_closed(change, error):
    nodes, _, mapping = graph()
    change(mapping)
    with pytest.raises((ValueError, ValidationError), match=error):
        _assistant_contract(deepcopy(nodes), mapping)


def test_choice_without_result_variable_is_rejected():
    nodes, ids, mapping = graph()
    next(node for node in nodes if node["id"] == str(ids["services"]))["data"]["result_variable"] = ""
    with pytest.raises(ValueError, match="assistant_service_selection_variable_invalid"):
        _assistant_contract(nodes, mapping)


def test_clinic_target_without_canonical_placeholder_is_rejected():
    nodes, ids, mapping = graph()
    next(node for node in nodes if node["id"] == str(ids["clinic"]))["data"]["content"] = "Clínica antiga"
    with pytest.raises(ValueError, match="assistant_clinic_name_placeholder_missing"):
        _assistant_contract(nodes, mapping)


@pytest.mark.parametrize("extra", [
    "manifest", "capabilities", "assistant_materialization", "nodes", "edges",
    "tool_name", "connection_id", "tenant_id", "template_node_key",
])
def test_promotion_request_forbids_mass_assignment(extra):
    payload = {
        "name": "Assistant", "category": "Agendamentos", "segment": "Geral",
        "modality": "Híbrido", "level": "Híbrido", "estimated_time": "5 min",
        "version": "1.0.0", extra: {},
    }
    with pytest.raises(ValidationError):
        PromoteTemplateBody.model_validate(payload)


def test_common_template_does_not_require_mapping():
    body = PromoteTemplateBody.model_validate({
        "name": "Fluxo comum", "category": "Atendimento", "segment": "Geral",
        "modality": "Sem IA", "level": "Determinístico", "estimated_time": "5 min",
        "version": "1.0.0",
    })
    assert body.template_kind == "flow"
    assert body.assistant_mapping is None
