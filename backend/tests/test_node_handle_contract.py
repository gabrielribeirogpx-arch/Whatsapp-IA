<<<<<<< HEAD
from app.flow_v2.node_handle_contract import (
    canonical_node_handles,
    migrate_legacy_edge_handles,
    normalize_handle,
)
from app.flow_v2.graph_validator import FlowV2GraphValidator


def test_canonical_contract_covers_branching_node_types() -> None:
    assert canonical_node_handles({"type": "mcp_tool"}) == ({"success", "error", "timeout"}, {"default"})
    assert canonical_node_handles({"type": "condition"})[0] == {"true", "false"}
    assert canonical_node_handles({"type": "choice_dynamic"})[0] == {"default"}
    assert canonical_node_handles({"type": "message"})[0] == {"default"}
    assert canonical_node_handles({"type": "action"})[0] == {"default"}
    assert canonical_node_handles({"type": "data_collection"})[0] == {"success", "invalid", "cancel", "timeout"}


def test_legacy_aliases_are_migrated_without_guessing_missing_mcp_branch() -> None:
    edges = [{"sourceHandle": "sucesso"}, {"source_handle": "erro"}, {"sourceHandle": "tempo_esgotado"}, {}]
    migrated = migrate_legacy_edge_handles(edges)
    assert [edge.get("sourceHandle") for edge in migrated] == ["success", "error", "timeout", None]
    assert normalize_handle(None) == ""


def test_validator_preserves_all_three_mcp_branches() -> None:
    nodes = [
        {"id": "mcp", "type": "mcp_tool", "data": {"isStart": True}},
        {"id": "next", "type": "message", "data": {"isEnd": True}},
    ]
    edges = [{"id": handle, "source": "mcp", "target": "next", "sourceHandle": handle} for handle in ("success", "error", "timeout")]
    result = FlowV2GraphValidator().validate(nodes=nodes, edges=edges)
    assert not any("HANDLE_NOT_FOUND" in error for error in result.errors)


def test_validator_reports_source_and_target_handle_errors_together() -> None:
    nodes = [{"id": "start", "type": "message", "data": {"isStart": True}}, {"id": "end", "type": "message", "data": {"isEnd": True}}]
    edges = [{"id": "bad", "source": "start", "target": "end", "sourceHandle": "missing", "targetHandle": "missing"}]
    errors = FlowV2GraphValidator().validate(nodes=nodes, edges=edges).errors
    assert any("SOURCE_HANDLE_NOT_FOUND" in error for error in errors)
    assert any("TARGET_HANDLE_NOT_FOUND" in error for error in errors)
=======
from app.flow_v2.node_handle_contract import get_node_handle_contract, migrate_edge_handles
from app.flow_v2.graph_validator import FlowV2GraphValidator


EXPECTED = {
    "mcp_tool": (["success", "error", "timeout"], ["default"]),
    "choice_dynamic": (["selected"], ["default"]),
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
>>>>>>> origin/main
