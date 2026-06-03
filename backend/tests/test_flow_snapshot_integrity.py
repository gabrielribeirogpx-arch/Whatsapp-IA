from __future__ import annotations

from uuid import uuid4
import os

os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")


from app.models import FlowVersion
from app.services.flow_engine_service import (
    apply_flow_version_snapshot_metadata,
    validate_flow_graph,
    validate_flow_version_integrity,
)


def _published_graph(message: str = "Olá") -> tuple[list[dict], list[dict]]:
    start_id = str(uuid4())
    end_id = str(uuid4())
    nodes = [
        {"id": start_id, "type": "message", "position": {"x": 0, "y": 0}, "data": {"isStart": True, "text": message}},
        {"id": end_id, "type": "message", "position": {"x": 200, "y": 0}, "data": {"text": "Fim", "isTerminal": True}},
    ]
    edges = [{"id": str(uuid4()), "source": start_id, "target": end_id, "sourceHandle": "default", "targetHandle": "default"}]
    return nodes, edges


def test_flow_version_snapshot_metadata_matches_builder_graph() -> None:
    nodes, edges = _published_graph()
    version = FlowVersion(flow_id=uuid4(), tenant_id=uuid4(), version=1)

    apply_flow_version_snapshot_metadata(version, nodes, edges)

    assert version.nodes_json == nodes
    assert version.edges_json == edges
    assert version.nodes_count == 2
    assert version.edges_count == 1
    assert version.graph_hash
    assert validate_flow_version_integrity(version) == (True, None)


def test_removed_node_is_not_present_after_snapshot_rebuild() -> None:
    nodes, edges = _published_graph()
    removed_node_id = nodes[-1]["id"]
    rebuilt_nodes = nodes[:1]
    rebuilt_nodes[0]["data"]["isTerminal"] = True
    rebuilt_edges: list[dict] = []
    version = FlowVersion(flow_id=uuid4(), tenant_id=uuid4(), version=2)

    apply_flow_version_snapshot_metadata(version, rebuilt_nodes, rebuilt_edges)

    assert removed_node_id not in {node["id"] for node in version.nodes_json}
    assert version.nodes_count == 1
    assert version.edges_count == 0


def test_runtime_aborts_when_snapshot_hash_is_invalid() -> None:
    nodes, edges = _published_graph("Mensagem antiga")
    version = FlowVersion(flow_id=uuid4(), tenant_id=uuid4(), version=1)
    apply_flow_version_snapshot_metadata(version, nodes, edges)
    version.nodes_json[0]["data"]["text"] = "Mensagem nova sem atualizar hash"

    valid, reason = validate_flow_version_integrity(version)

    assert valid is False
    assert reason == "FLOW_VERSION_GRAPH_HASH_MISMATCH"


def test_choice_edges_must_point_to_existing_nodes() -> None:
    choice_id = str(uuid4())
    target_a = str(uuid4())
    target_b = str(uuid4())
    nodes = [
        {"id": choice_id, "type": "choice", "data": {"isStart": True, "content": "Escolha", "options": [{"label": "A", "handleId": "a"}, {"label": "B", "handleId": "b"}]}},
        {"id": target_a, "type": "message", "data": {"text": "A", "isTerminal": True}},
        {"id": target_b, "type": "message", "data": {"text": "B", "isTerminal": True}},
    ]
    edges = [
        {"source": choice_id, "target": target_a, "sourceHandle": "a"},
        {"source": choice_id, "target": target_b, "sourceHandle": "b"},
        {"source": choice_id, "target": str(uuid4()), "sourceHandle": "missing"},
    ]

    result = validate_flow_graph(nodes, edges, mode="publish")

    assert result["valid"] is False
    assert any(issue["code"] == "EDGE_REFERENCE_NOT_FOUND" for issue in result["errors"])


def test_published_snapshot_keeps_sessions_version_specific() -> None:
    old_nodes, old_edges = _published_graph("Antiga")
    new_nodes, new_edges = _published_graph("Nova")
    flow_id = uuid4()
    tenant_id = uuid4()
    old_version = FlowVersion(id=uuid4(), flow_id=flow_id, tenant_id=tenant_id, version=1)
    new_version = FlowVersion(id=uuid4(), flow_id=flow_id, tenant_id=tenant_id, version=2)

    apply_flow_version_snapshot_metadata(old_version, old_nodes, old_edges)
    apply_flow_version_snapshot_metadata(new_version, new_nodes, new_edges)

    assert old_version.id != new_version.id
    assert old_version.graph_hash != new_version.graph_hash
    assert old_version.nodes_json[0]["data"]["text"] == "Antiga"
    assert new_version.nodes_json[0]["data"]["text"] == "Nova"
