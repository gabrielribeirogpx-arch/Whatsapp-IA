from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.schemas.assistant_configuration import AssistantConfigurationV1, AssistantMaterializationRequest
from app.services.assistant_materialization_service import _contract, build_candidate_graph


def configuration():
    return AssistantConfigurationV1.model_validate({
        "schema_version": 1,
        "clinic_name": "Clínica Segura",
        "services": [
            {"id": "consulta", "label": "Consulta", "duration_minutes": 30},
            {"id": "avaliacao", "label": "Avaliação", "duration_minutes": 45},
        ],
        "google_calendar_connection_id": str(uuid4()),
        "handoff": {"enabled": True, "reason": "Atendimento humano solicitado"},
    })


def graph():
    nodes = [
        {"id": "1", "type": "message", "data": {"template_node_key": "welcome", "message": "old", "untouched": {"a": 1}}},
        {"id": "2", "type": "choice", "data": {"template_node_key": "service_choice", "options": [{"id": "old"}], "result_variable": "appointment_type"}},
        {"id": "3", "type": "mcp_tool", "data": {"template_node_key": "calendar", "connection_id": "integration:old", "tool_name": "calendar.availability"}},
        {"id": "4", "type": "action", "data": {"template_node_key": "handoff", "reason": "old", "action_type": "transfer_human"}},
    ]
    edges = [{"id": "e", "source": "1", "target": "2", "sourceHandle": "selected"}]
    return nodes, edges


TARGETS = [
    {"parameter": "clinic_name", "node_key": "welcome", "field": "data.message"},
    {"parameter": "services", "node_key": "service_choice", "field": "data.options"},
    {"parameter": "google_calendar_connection_id", "node_key": "calendar", "field": "data.connection_id"},
    {"parameter": "handoff.reason", "node_key": "handoff", "field": "data.reason"},
]


def test_materialization_changes_only_declared_fields_and_ignores_duration():
    nodes, edges = graph()
    original_nodes, original_edges = deepcopy(nodes), deepcopy(edges)
    candidate, candidate_edges, changed = build_candidate_graph(nodes, edges, configuration(), TARGETS)
    assert nodes == original_nodes and edges == original_edges  # in-memory copy, never incremental persistence
    assert candidate_edges == original_edges
    assert candidate[0]["data"] == {"template_node_key": "welcome", "message": "Clínica Segura", "untouched": {"a": 1}}
    assert candidate[1]["data"]["options"] == [
        {"id": "consulta", "label": "Consulta", "value": "consulta"},
        {"id": "avaliacao", "label": "Avaliação", "value": "avaliacao"},
    ]
    assert "duration_minutes" not in repr(candidate)
    assert candidate[1]["data"]["result_variable"] == "appointment_type"
    assert candidate[2]["data"]["tool_name"] == "calendar.availability"
    assert changed == ["clinic_name", "google_calendar_connection_id", "handoff.reason", "services"]


def test_missing_or_duplicate_stable_node_key_fails_before_mutation():
    nodes, edges = graph()
    with pytest.raises(HTTPException, match="materialization_target_not_found"):
        build_candidate_graph(nodes, edges, configuration(), [{"parameter": "clinic_name", "node_key": "missing", "field": "data.message"}])
    nodes.append(deepcopy(nodes[0]))
    with pytest.raises(HTTPException, match="duplicate_template_node_key"):
        build_candidate_graph(nodes, edges, configuration(), TARGETS)


def test_template_contract_rejects_unknown_fields_duplicates_and_missing_capability():
    def version(targets, capabilities=("appointment_assistant_configuration",)):
        return SimpleNamespace(manifest={
            "capabilities": list(capabilities),
            "assistant_materialization": {"schema_version": 1, "service_selection_variable": "appointment_type", "targets": targets},
        })

    assert _contract(version(TARGETS)) == TARGETS
    forbidden = [{"parameter": "services", "node_key": "service_choice", "field": "data.tool_name"}]
    with pytest.raises(HTTPException, match="materialization_target_not_allowed"):
        _contract(version(forbidden))
    with pytest.raises(HTTPException, match="duplicate_materialization_target"):
        _contract(version([TARGETS[0], TARGETS[0]]))
    with pytest.raises(HTTPException, match="template_does_not_support_materialization"):
        _contract(version(TARGETS, capabilities=()))

    missing_binding = SimpleNamespace(manifest={
        "capabilities": ["appointment_assistant_configuration"],
        "assistant_materialization": {"schema_version": 1, "targets": TARGETS},
    })
    with pytest.raises(HTTPException, match="invalid_materialization_contract"):
        _contract(missing_binding)


@pytest.mark.parametrize("extra", ["node_id", "path", "nodes", "edges", "tool_name", "connection_id"])
def test_endpoint_payload_forbids_structural_or_arbitrary_binding_fields(extra):
    payload = {"expected_configuration_version": 1, "expected_managed_flow_version_id": str(uuid4()), extra: "attacker"}
    with pytest.raises(ValidationError):
        AssistantMaterializationRequest.model_validate(payload)
