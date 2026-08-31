from app.flow_v2.node_handle_contract import get_node_handle_contract, migrate_edge_handles
from app.flow_v2.graph_validator import FlowV2GraphValidator


EXPECTED = {
    "mcp_tool": (["success", "error", "timeout"], ["default"]),
    "choice_dynamic": (["selected", "empty"], ["default"]),
    "data_collection": (["success", "cancel", "timeout", "invalid"], ["default"]),
    "condition": (["true", "false"], ["default"]),
    "message": (["default"], ["default"]),
    "action": (["default"], ["default"]),
}


def test_publisher_handle_contract_parity_matrix():
    for node_type, (sources, targets) in EXPECTED.items():
        contract = get_node_handle_contract({"id": node_type, "type": node_type, "data": {}})
        assert contract == {"sourceHandles": sources, "targetHandles": targets}


def test_mcp_edges_and_legacy_aliases_survive_save_reload_and_snapshot():
    nodes = [
        {"id": "mcp", "type": "mcp_tool", "data": {}},
        {"id": "message", "type": "message", "data": {}},
        {"id": "action", "type": "action", "data": {}},
    ]
    edges = [
        {"id": "success", "source": "mcp", "target": "message", "sourceHandle": "sucesso"},
        {"id": "error", "source": "mcp", "target": "message", "sourceHandle": "erro"},
        {"id": "timeout", "source": "mcp", "target": "action", "sourceHandle": "tempo_esgotado"},
    ]
    saved = migrate_edge_handles(nodes, edges)
    reloaded = migrate_edge_handles(nodes, saved)
    snapshot = migrate_edge_handles(nodes, reloaded)
    assert [edge["sourceHandle"] for edge in snapshot] == ["success", "error", "timeout"]
    assert all(edge.get("targetHandle") in (None, "default") for edge in snapshot)


def test_action_declared_handles_override_default():
    contract = get_node_handle_contract({"type": "action", "data": {"source_handles": ["done", "failed"]}})
    assert contract["sourceHandles"] == ["done", "failed"]


def test_dynamic_choice_selected_to_data_collection_default_is_publishable():
    nodes = [
        {"id": "start", "type": "start", "data": {}},
        {"id": "dynamic", "type": "choice_dynamic", "data": {"options_variable": "slots", "label_field": "label", "value_field": "id"}},
        {"id": "collection", "type": "data_collection", "data": {}},
    ]
    edge = {
        "id": "dynamic-collection",
        "source": "dynamic",
        "sourceHandle": "selected",
        "target": "collection",
        "targetHandle": "default",
    }
    saved = migrate_edge_handles(nodes, [{"id": "start-dynamic", "source": "start", "target": "dynamic"}, edge])
    reloaded = migrate_edge_handles(nodes, saved)
    result = FlowV2GraphValidator().validate(nodes=nodes, edges=reloaded)

    assert result.is_valid
    assert reloaded[1]["sourceHandle"] == "selected"
    assert reloaded[1]["targetHandle"] == "default"


def test_two_mcps_publish_contract_accepts_every_branch():
    nodes = [
        {"id": "start", "type": "message", "data": {"isStart": True, "content": "start"}},
        {"id": "mcp1", "type": "mcp_tool", "data": {}},
        {"id": "mcp2", "type": "mcp_tool", "data": {}},
        {"id": "success", "type": "message", "data": {"content": "ok", "is_terminal": True}},
        {"id": "error", "type": "message", "data": {"content": "error", "is_terminal": True}},
        {"id": "timeout", "type": "action", "data": {"is_terminal": True}},
    ]
    edges = [
        {"id": "start-mcp", "source": "start", "target": "mcp1"},
        {"id": "chain", "source": "mcp1", "sourceHandle": "success", "target": "mcp2"},
        {"id": "mcp1-error", "source": "mcp1", "sourceHandle": "error", "target": "error"},
        {"id": "mcp1-timeout", "source": "mcp1", "sourceHandle": "timeout", "target": "timeout"},
        {"id": "mcp2-success", "source": "mcp2", "sourceHandle": "success", "target": "success"},
        {"id": "mcp2-error", "source": "mcp2", "sourceHandle": "error", "target": "error"},
        {"id": "mcp2-timeout", "source": "mcp2", "sourceHandle": "timeout", "target": "timeout"},
    ]
    assert FlowV2GraphValidator().validate(nodes=nodes, edges=edges).is_valid
