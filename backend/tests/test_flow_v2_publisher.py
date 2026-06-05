from __future__ import annotations

import pytest

from app.flow_v2.graph_validator import FlowV2GraphValidator, GraphValidationStatus
from app.flow_v2.publisher import FlowV2PublishError, FlowV2Publisher, v2_snapshot_hash
from app.flow_v2.snapshot_viewer import FlowV2SnapshotViewer


def _valid_nodes() -> list[dict]:
    return [
        {"id": "start", "type": "message", "content": "Olá"},
        {
            "id": "choice",
            "type": "choice",
            "options": [{"id": "yes", "label": "Sim"}, {"id": "no", "label": "Não"}],
        },
        {"id": "delay", "type": "delay", "seconds": 1},
        {
            "id": "condition",
            "type": "condition",
            "conditions": [{"field": "accepted", "operator": "==", "value": True}],
        },
        {"id": "end", "type": "message", "content": "Fim"},
    ]


def _valid_edges() -> list[dict]:
    return [
        {"id": "e1", "source": "start", "target": "choice"},
        {"id": "e2", "source": "choice", "sourceHandle": "yes", "target": "delay"},
        {"id": "e3", "source": "choice", "sourceHandle": "no", "target": "end"},
        {"id": "e4", "source": "delay", "target": "condition"},
        {"id": "e5", "source": "condition", "sourceHandle": "true", "target": "end"},
        {"id": "e6", "source": "condition", "sourceHandle": "false", "target": "end"},
    ]


def test_duplicate_start_is_invalid() -> None:
    nodes = _valid_nodes() + [{"id": "second", "type": "start"}]

    result = FlowV2GraphValidator().validate(nodes=nodes, edges=_valid_edges())

    assert result.status == GraphValidationStatus.INVALID
    assert "FLOW_V2_REQUIRES_EXACTLY_ONE_START_NODE" in result.errors


def test_orphan_node_is_invalid() -> None:
    nodes = _valid_nodes() + [{"id": "orphan", "type": "message", "content": "Perdido"}]

    result = FlowV2GraphValidator().validate(nodes=nodes, edges=_valid_edges())

    assert result.status == GraphValidationStatus.INVALID
    assert "FLOW_V2_ORPHAN_NODE:orphan" in result.errors
    assert "FLOW_V2_UNREACHABLE_NODE:orphan" in result.errors


def test_broken_edge_is_invalid() -> None:
    edges = _valid_edges() + [
        {"id": "broken", "source": "missing-source", "target": "missing-target"}
    ]

    result = FlowV2GraphValidator().validate(nodes=_valid_nodes(), edges=edges)

    assert result.status == GraphValidationStatus.INVALID
    assert "FLOW_V2_EDGE_SOURCE_NOT_FOUND:missing-source" in result.errors
    assert "FLOW_V2_EDGE_TARGET_NOT_FOUND:missing-target" in result.errors
    assert "FLOW_V2_BROKEN_EDGE:broken" in result.errors


def test_choice_without_option_id_or_source_handle_is_invalid() -> None:
    nodes = _valid_nodes()
    nodes[1] = {"id": "choice", "type": "choice", "options": [{"label": "Sem id"}]}
    edges = [
        {"id": "e1", "source": "start", "target": "choice"},
        {"id": "e2", "source": "choice", "target": "end"},
    ]

    result = FlowV2GraphValidator().validate(nodes=nodes, edges=edges)

    assert result.status == GraphValidationStatus.INVALID
    assert "FLOW_V2_CHOICE_OPTION_ID_REQUIRED:choice:0" in result.errors
    assert "FLOW_V2_CHOICE_SOURCE_HANDLE_REQUIRED:choice:1" in result.errors


@pytest.mark.parametrize("seconds", [0, -1, None, "abc"])
def test_delay_seconds_must_be_positive(seconds) -> None:
    nodes = _valid_nodes()
    nodes[2] = {"id": "delay", "type": "delay", "seconds": seconds}

    result = FlowV2GraphValidator().validate(nodes=nodes, edges=_valid_edges())

    assert result.status == GraphValidationStatus.INVALID
    assert "FLOW_V2_DELAY_SECONDS_MUST_BE_POSITIVE:delay" in result.errors


def test_invalid_condition_config_is_invalid() -> None:
    nodes = _valid_nodes()
    nodes[3] = {
        "id": "condition",
        "type": "condition",
        "conditions": [{"field": "accepted", "operator": "contains"}],
    }

    result = FlowV2GraphValidator().validate(nodes=nodes, edges=_valid_edges())

    assert result.status == GraphValidationStatus.INVALID
    assert "FLOW_V2_CONDITION_CONFIG_INVALID:condition:0" in result.errors


def test_snapshot_hash_is_deterministic_for_json_key_and_graph_order() -> None:
    nodes = _valid_nodes()
    edges = _valid_edges()
    reordered_nodes = [dict(reversed(list(node.items()))) for node in reversed(nodes)]
    reordered_edges = [dict(reversed(list(edge.items()))) for edge in reversed(edges)]

    assert v2_snapshot_hash(nodes, edges) == v2_snapshot_hash(
        reordered_nodes, reordered_edges
    )


def test_valid_publication_builds_immutable_snapshot_and_viewer() -> None:
    result = FlowV2Publisher().publish(nodes=_valid_nodes(), edges=_valid_edges())

    assert result.validation.status == GraphValidationStatus.VALID
    assert result.snapshot["version"] == "flow_v2_snapshot_v1"
    assert result.snapshot["hash"] == result.v2_snapshot_hash
    assert result.snapshot["start_node_id"] == "start"
    assert len(result.snapshot["nodes"]) == 5
    assert len(result.snapshot["edges"]) == 6
    assert result.snapshot["transitions"] == [
        {"id": "e1", "source_node_id": "start", "target_node_id": "choice", "edge_id": "e1"},
        {"id": "e2", "source_node_id": "choice", "target_node_id": "delay", "source_handle": "yes", "edge_id": "e2"},
        {"id": "e3", "source_node_id": "choice", "target_node_id": "end", "source_handle": "no", "edge_id": "e3"},
        {"id": "e4", "source_node_id": "delay", "target_node_id": "condition", "edge_id": "e4"},
        {"id": "e5", "source_node_id": "condition", "target_node_id": "end", "source_handle": "true", "edge_id": "e5"},
        {"id": "e6", "source_node_id": "condition", "target_node_id": "end", "source_handle": "false", "edge_id": "e6"},
    ]

    view = FlowV2SnapshotViewer().view(result.snapshot).as_dict()
    assert view["version"] == "flow_v2_snapshot_v1"
    assert view["hash"] == result.v2_snapshot_hash
    assert view["nodes_count"] == 5
    assert view["edges_count"] == 6
    assert view["snapshot"] == result.snapshot


def test_publisher_raises_with_validation_errors() -> None:
    with pytest.raises(FlowV2PublishError) as exc:
        FlowV2Publisher().publish(
            nodes=[
                {"id": "start", "type": "message"},
                {"id": "orphan", "type": "message"},
            ],
            edges=[],
        )

    assert "FLOW_V2_ORPHAN_NODE:orphan" in exc.value.errors
