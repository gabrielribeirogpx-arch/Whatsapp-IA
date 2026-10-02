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


def test_provider_agnostic_binding_reference_is_materialized_server_side():
    nodes, edges = graph()
    binding_id = uuid4()
    candidate, _, _ = build_candidate_graph(
        nodes, edges, configuration(), TARGETS,
        calendar_connection_reference=f"assistant_calendar:{binding_id}",
    )
    assert candidate[2]["data"]["connection_id"] == f"assistant_calendar:{binding_id}"


def test_service_handles_are_correlated_by_id_then_value_then_unambiguous_label():
    nodes, edges = graph()
    source_nodes = deepcopy(nodes)
    source_nodes[1]["data"]["options"] = [
        {"id": "consulta", "label": "Antiga", "value": "outro", "sourceHandle": "by-id"},
        {"id": "legacy-avaliacao", "label": "Antiga", "value": "avaliacao", "source_handle": "by-value"},
    ]

    candidate, _, _ = build_candidate_graph(
        nodes, edges, configuration(), [TARGETS[1]], source_nodes=source_nodes,
    )

    assert candidate[1]["data"]["options"] == [
        {"id": "consulta", "label": "Consulta", "value": "consulta", "sourceHandle": "by-id"},
        {"id": "avaliacao", "label": "Avaliação", "value": "avaliacao", "source_handle": "by-value"},
    ]


def test_service_materialization_does_not_invent_handle_for_ambiguous_label():
    nodes, edges = graph()
    source_nodes = deepcopy(nodes)
    source_nodes[1]["data"]["options"] = [
        {"id": "old-1", "label": "Consulta", "source_handle": "first"},
        {"id": "old-2", "label": "Consulta", "source_handle": "second"},
    ]
    configured = configuration()
    configured.services = [configured.services[0]]

    candidate, _, _ = build_candidate_graph(
        nodes, edges, configured, [TARGETS[1]], source_nodes=source_nodes,
    )

    assert candidate[1]["data"]["options"] == [
        {"id": "consulta", "label": "Consulta", "value": "consulta"},
    ]


def test_clinic_name_interpolation_preserves_surrounding_message_and_is_idempotent():
    nodes, edges = graph()
    nodes[0]["data"]["message"] = "Olá! Bem-vindo à {{clinic_name}}. Como posso ajudar?"
    targets = [{**TARGETS[0], "operation": "interpolate"}]

    candidate, candidate_edges, changed = build_candidate_graph(nodes, edges, configuration(), targets)

    assert candidate[0]["data"]["message"] == "Olá! Bem-vindo à Clínica Segura. Como posso ajudar?"
    assert candidate_edges == edges
    assert changed == ["clinic_name"]
    repeated, _, repeated_changed = build_candidate_graph(
        candidate, candidate_edges, configuration(), targets, source_nodes=nodes,
    )
    assert repeated == candidate
    assert repeated_changed == []


@pytest.mark.parametrize("message", ["Bem-vindo à clínica", "Bem-vindo à {{company_name}}"])
def test_clinic_name_interpolation_rejects_missing_or_wrong_placeholder(message):
    nodes, edges = graph()
    nodes[0]["data"]["message"] = message
    with pytest.raises(HTTPException, match="materialization_placeholder_missing"):
        build_candidate_graph(nodes, edges, configuration(), [{**TARGETS[0], "operation": "interpolate"}])


def test_interpolation_uses_trusted_source_snapshot_for_configuration_updates():
    source_nodes, edges = graph()
    source_nodes[0]["data"]["message"] = "Bem-vindo à {{clinic_name}}"
    installed = deepcopy(source_nodes)
    installed[0]["data"]["message"] = "Bem-vindo à Clínica Antiga"
    candidate, _, _ = build_candidate_graph(
        installed, edges, configuration(), [{**TARGETS[0], "operation": "interpolate"}],
        source_nodes=source_nodes,
    )
    assert candidate[0]["data"]["message"] == "Bem-vindo à Clínica Segura"


def test_materialization_binds_every_declared_calendar_target_only():
    nodes, edges = graph()
    nodes[2]["data"]["template_node_key"] = "availability"
    for key, tool in (("create", "google_calendar_create_event"), ("find", "google_calendar_find_managed_appointments"), ("update", "google_calendar_update_event")):
        nodes.append({"id": key, "type": "mcp_tool", "data": {"template_node_key": key, "connection_id": "integration:old", "tool_name": tool, "arguments": {"keep": True}}})
    nodes.append({"id": "undeclared", "type": "mcp_tool", "data": {"template_node_key": "other", "connection_id": "integration:old", "tool_name": "unchanged"}})
    targets = [
        {"parameter": "google_calendar_connection_id", "node_key": key, "field": "data.connection_id"}
        for key in ("availability", "create", "find", "update")
    ]
    configured = configuration()
    candidate, _, _ = build_candidate_graph(nodes, edges, configured, targets)
    expected = f"integration:{configured.google_calendar_connection_id}"
    assert all(node["data"]["connection_id"] == expected for node in candidate if node["data"].get("template_node_key") in {"availability", "create", "find", "update"})
    assert candidate[-1]["data"] == nodes[-1]["data"]
    assert next(node for node in candidate if node["id"] == "create")["data"]["arguments"] == {"keep": True}


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
    interpolated = [{**TARGETS[0], "operation": "interpolate"}]
    assert _contract(version(interpolated)) == interpolated
    with pytest.raises(HTTPException, match="materialization_operation_not_allowed"):
        _contract(version([{**TARGETS[1], "operation": "interpolate"}]))
    with pytest.raises(HTTPException, match="materialization_operation_not_allowed"):
        _contract(version([{**TARGETS[0], "operation": "evaluate"}]))
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
