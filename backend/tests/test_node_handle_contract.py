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
