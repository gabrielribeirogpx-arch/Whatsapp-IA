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


def test_legacy_delay_content_is_promoted_to_seconds_before_validation() -> None:
    nodes = _valid_nodes()
    nodes[2] = {"id": "delay", "type": "delay", "data": {"content": "5"}}

    result = FlowV2Publisher().publish(nodes=nodes, edges=_valid_edges())

    delay_node = next(node for node in result.snapshot["nodes"] if node["id"] == "delay")
    assert delay_node["seconds"] == 5
    assert "content" not in delay_node.get("data", {})


@pytest.mark.parametrize("seconds", [0, -1, None, "abc"])
def test_delay_seconds_must_be_positive(seconds) -> None:
    nodes = _valid_nodes()
    nodes[2] = {"id": "delay", "type": "delay", "seconds": seconds}

    result = FlowV2GraphValidator().validate(nodes=nodes, edges=_valid_edges())

    assert result.status == GraphValidationStatus.INVALID
    assert "FLOW_V2_DELAY_SECONDS_MUST_BE_POSITIVE:delay" in result.errors


def test_flow_builder_condition_keywords_match_type_is_valid() -> None:
    nodes = _valid_nodes()
    nodes[3] = {
        "id": "condition",
        "type": "condition",
        "data": {"keywords": ["suporte"], "matchType": "contains"},
    }

    result = FlowV2GraphValidator().validate(nodes=nodes, edges=_valid_edges())

    assert result.status == GraphValidationStatus.VALID


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
        {
            "id": "e1",
            "source_node_id": "start",
            "target_node_id": "choice",
            "edge_id": "e1",
        },
        {
            "id": "e2",
            "source_node_id": "choice",
            "target_node_id": "delay",
            "source_handle": "yes",
            "edge_id": "e2",
        },
        {
            "id": "e3",
            "source_node_id": "choice",
            "target_node_id": "end",
            "source_handle": "no",
            "edge_id": "e3",
        },
        {
            "id": "e4",
            "source_node_id": "delay",
            "target_node_id": "condition",
            "edge_id": "e4",
        },
        {
            "id": "e5",
            "source_node_id": "condition",
            "target_node_id": "end",
            "source_handle": "true",
            "edge_id": "e5",
        },
        {
            "id": "e6",
            "source_node_id": "condition",
            "target_node_id": "end",
            "source_handle": "false",
            "edge_id": "e6",
        },
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


def _choice_button_nodes() -> list[dict]:
    return [
        {"id": "start", "type": "message", "data": {"content": "Olá"}},
        {
            "id": "choice",
            "type": "choice",
            "data": {
                "content": "Escolha",
                "buttons": [
                    {
                        "id": "choice-1",
                        "label": "Quero planos",
                        "handleId": "quero_planos",
                        "next": "",
                    },
                    {
                        "id": "choice-2",
                        "label": "Falar com humano",
                        "handleId": "falar_com_humano",
                        "next": "",
                    },
                ],
            },
        },
        {"id": "end", "type": "message", "data": {"content": "Fim"}},
    ]


def _choice_edges() -> list[dict]:
    return [
        {"id": "e1", "source": "start", "target": "choice"},
        {
            "id": "e2",
            "source": "choice",
            "sourceHandle": "quero_planos",
            "target": "end",
        },
        {
            "id": "e3",
            "source": "choice",
            "sourceHandle": "falar_com_humano",
            "target": "end",
        },
    ]


def _snapshot_node(snapshot: dict, node_id: str) -> dict:
    return next(node for node in snapshot["nodes"] if node["id"] == node_id)


def test_publisher_converts_legacy_builder_choice_buttons_to_runtime_options() -> None:
    nodes = _choice_button_nodes()

    result = FlowV2Publisher().publish(nodes=nodes, edges=_choice_edges())

    choice = _snapshot_node(result.snapshot, "choice")
    assert choice["data"]["options"] == [
        {"id": "quero_planos", "label": "Quero planos"},
        {"id": "falar_com_humano", "label": "Falar com humano"},
    ]
    assert choice["data"]["buttons"] == nodes[1]["data"]["buttons"]
    assert "options" not in nodes[1]["data"]


def test_publisher_keeps_choice_options_for_new_runtime_contract_flows() -> None:
    nodes = _choice_button_nodes()
    nodes[1] = {
        "id": "choice",
        "type": "choice",
        "data": {
            "content": "Escolha",
            "options": [
                {"id": "quero_planos", "label": "Quero planos"},
                {"id": "falar_com_humano", "label": "Falar com humano"},
            ],
        },
    }

    result = FlowV2Publisher().publish(nodes=nodes, edges=_choice_edges())

    choice = _snapshot_node(result.snapshot, "choice")
    assert choice["data"]["options"] == nodes[1]["data"]["options"]
    assert "buttons" not in choice["data"]


def test_publisher_does_not_override_existing_choice_options_with_buttons() -> None:
    nodes = _choice_button_nodes()
    nodes[1]["data"]["options"] = [{"id": "existing", "label": "Existente"}]

    result = FlowV2Publisher().publish(nodes=nodes, edges=_choice_edges())

    choice = _snapshot_node(result.snapshot, "choice")
    assert choice["data"]["options"] == [{"id": "existing", "label": "Existente"}]
    assert choice["data"]["buttons"] == nodes[1]["data"]["buttons"]


def test_publisher_migrates_legacy_buttons_node_to_choice_display_mode_buttons() -> None:
    nodes = [
        {"id": "start", "type": "message", "data": {"isStart": True, "content": "Olá"}},
        {
            "id": "legacy-buttons",
            "type": "buttons",
            "data": {
                "body_text": "Escolha",
                "buttons": [{"id": "btn-1", "label": "Vendas", "handleId": "vendas"}],
            },
        },
        {"id": "end", "type": "message", "data": {"content": "Fim"}},
    ]
    edges = [
        {"id": "e1", "source": "start", "target": "legacy-buttons"},
        {"id": "e2", "source": "legacy-buttons", "sourceHandle": "vendas", "target": "end"},
    ]

    result = FlowV2Publisher().publish(nodes=nodes, edges=edges)

    choice = _snapshot_node(result.snapshot, "legacy-buttons")
    assert choice["type"] == "choice"
    assert choice["data"]["display_mode"] == "buttons"
    assert choice["data"]["options"] == [{"id": "vendas", "label": "Vendas"}]
    assert choice["data"]["buttons"] == nodes[1]["data"]["buttons"]


def test_publisher_migrates_legacy_list_node_to_choice_display_mode_list() -> None:
    nodes = [
        {"id": "start", "type": "message", "data": {"isStart": True, "content": "Olá"}},
        {
            "id": "legacy-list",
            "type": "list",
            "data": {
                "body_text": "Escolha",
                "sections": [{"title": "Áreas", "rows": [{"id": "row-1", "title": "Suporte", "handleId": "suporte"}]}],
            },
        },
        {"id": "end", "type": "message", "data": {"content": "Fim"}},
    ]
    edges = [
        {"id": "e1", "source": "start", "target": "legacy-list"},
        {"id": "e2", "source": "legacy-list", "sourceHandle": "suporte", "target": "end"},
    ]

    result = FlowV2Publisher().publish(nodes=nodes, edges=edges)

    choice = _snapshot_node(result.snapshot, "legacy-list")
    assert choice["type"] == "choice"
    assert choice["data"]["display_mode"] == "list"
    assert choice["data"]["options"] == [{"id": "suporte", "label": "Suporte"}]
    assert choice["data"]["sections"] == nodes[1]["data"]["sections"]


def test_media_node_publish_preserves_media_fields() -> None:
    nodes = [{"id": "start", "type": "message", "data": {"isStart": True, "content": "Olá"}}, {"id": "media", "type": "media", "data": {"media_type": "document", "media_url": "https://cdn.example.com/contrato.pdf", "caption": "Segue o PDF", "filename": "contrato.pdf"}}]
    edges = [{"id": "e1", "source": "start", "target": "media"}]
    result = FlowV2Publisher().publish(nodes=nodes, edges=edges)
    media_node = next(node for node in result.snapshot["nodes"] if node["id"] == "media")
    assert media_node["type"] == "media"
    assert media_node["data"]["media_type"] == "document"
    assert media_node["data"]["media_url"] == "https://cdn.example.com/contrato.pdf"
    assert media_node["data"]["caption"] == "Segue o PDF"
    assert media_node["data"]["filename"] == "contrato.pdf"


def test_media_node_requires_https_url() -> None:
    nodes = [{"id": "start", "type": "media", "data": {"isStart": True, "media_type": "image", "media_url": "http://cdn.example.com/foto.jpg"}}]
    result = FlowV2GraphValidator().validate(nodes=nodes, edges=[])
    assert result.status == GraphValidationStatus.INVALID
    assert "FLOW_V2_MEDIA_URL_INVALID:start" in result.errors
