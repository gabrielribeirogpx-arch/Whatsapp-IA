from __future__ import annotations

import pytest

from app.flow_v2.graph_validator import FlowV2GraphValidator, GraphValidationStatus
from app.flow_v2.publisher import FlowV2PublishError, FlowV2Publisher, v2_snapshot_hash
from app.flow_v2.snapshot_viewer import FlowV2SnapshotViewer
from app.flow_v2.node_executors import ConditionNodeExecutor


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


def test_visual_only_legacy_condition_is_invalid() -> None:
    nodes = _valid_nodes()
    nodes[3] = {
        "id": "condition",
        "type": "condition",
        "data": {"keywords": ["suporte"], "matchType": "contains"},
    }

    result = FlowV2GraphValidator().validate(nodes=nodes, edges=_valid_edges())

    assert result.status == GraphValidationStatus.INVALID
    assert "FLOW_V2_CONDITION_CONFIG_INVALID:condition" in result.errors


@pytest.mark.parametrize(
    "rule",
    [
        {},
        {"operator": "equals", "value": "outro"},
        {"field": "intent_category", "value": "outro"},
        {"field": "intent_category", "operator": "equals"},
        {"field": "intent_category", "operator": "contains", "value": "outro"},
    ],
)
def test_condition_requires_runtime_v2_variable_operator_and_value(rule) -> None:
    nodes = _valid_nodes()
    nodes[3] = {"id": "condition", "type": "condition", "conditions": [rule]}

    result = FlowV2GraphValidator().validate(nodes=nodes, edges=_valid_edges())

    assert result.status == GraphValidationStatus.INVALID


@pytest.mark.parametrize(
    ("intent_category", "expected"),
    [
        ("financeiro", False),
        ("vendas", False),
        ("suporte", False),
        ("outro", True),
        (None, False),
    ],
)
def test_marketplace_condition_evaluates_intent_category(intent_category, expected) -> None:
    rule = {"field": "intent_category", "operator": "equals", "value": "outro"}
    metadata = {} if intent_category is None else {"intent_category": intent_category}

    assert ConditionNodeExecutor._evaluate(rule, metadata) is expected


def test_condition_not_equals_is_valid_runtime_v2_configuration() -> None:
    nodes = _valid_nodes()
    nodes[3] = {
        "id": "condition",
        "type": "condition",
        "conditions": [
            {"field": "ai.classification", "operator": "!=", "value": "outro"}
        ],
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


def test_media_node_publish_preserves_uploaded_media_url_and_filename() -> None:
    nodes = [{"id": "start", "type": "media", "data": {"isStart": True, "media_type": "image", "media_url": "https://api.example.com/uploads/flow-media/tenant/foto.webp", "caption": "Veja", "filename": "foto.webp", "media_source": "upload"}}]
    result = FlowV2Publisher().publish(nodes=nodes, edges=[])
    media_node = next(node for node in result.snapshot["nodes"] if node["id"] == "start")
    assert media_node["data"]["media_type"] == "image"
    assert media_node["data"]["media_url"] == "https://api.example.com/uploads/flow-media/tenant/foto.webp"
    assert media_node["data"]["caption"] == "Veja"
    assert media_node["data"]["filename"] == "foto.webp"


def test_media_node_requires_https_url() -> None:
    nodes = [{"id": "start", "type": "media", "data": {"isStart": True, "media_type": "image", "media_url": "http://cdn.example.com/foto.jpg"}}]
    result = FlowV2GraphValidator().validate(nodes=nodes, edges=[])
    assert result.status == GraphValidationStatus.INVALID
    assert "FLOW_V2_MEDIA_URL_INVALID:start" in result.errors


def test_cta_url_node_publishes_without_unsupported_type_error() -> None:
    result = FlowV2Publisher().publish(
        nodes=[
            {"id": "start", "type": "message", "content": "Olá"},
            {
                "id": "cta",
                "type": "cta_url",
                "data": {
                    "content": "Veja nossos planos",
                    "button_text": "Abrir link",
                    "url": "https://example.com/planos",
                },
            },
        ],
        edges=[{"id": "e1", "source": "start", "target": "cta"}],
    )

    assert result.validation.status == GraphValidationStatus.VALID
    assert not any("FLOW_V2_NODE_TYPE_UNSUPPORTED" in error for error in result.validation.errors)
    cta_node = next(node for node in result.snapshot["nodes"] if node["id"] == "cta")
    assert cta_node["type"] == "cta_url"


def test_cta_url_without_https_fails_with_specific_error() -> None:
    result = FlowV2GraphValidator().validate(
        nodes=[
            {"id": "start", "type": "message", "content": "Olá"},
            {
                "id": "cta",
                "type": "cta_url",
                "data": {
                    "content": "Veja nossos planos",
                    "button_text": "Abrir link",
                    "url": "http://example.com/planos",
                },
            },
        ],
        edges=[{"id": "e1", "source": "start", "target": "cta"}],
    )

    assert result.status == GraphValidationStatus.INVALID
    assert "FLOW_V2_CTA_URL_HTTPS_REQUIRED:cta" in result.errors


def test_ai_rag_continue_to_next_requires_edge() -> None:
    nodes = [
        {"id": "start", "type": "ai_rag", "data": {"isStart": True, "after_answer_behavior": "continue_to_next"}},
        {"id": "next", "type": "message", "content": "Depois"},
    ]

    invalid = FlowV2GraphValidator().validate(nodes=nodes, edges=[])
    assert invalid.status == GraphValidationStatus.INVALID
    assert "FLOW_V2_AI_RAG_CONTINUE_TO_NEXT_REQUIRES_EDGE:start" in invalid.errors

    valid = FlowV2GraphValidator().validate(nodes=nodes, edges=[{"id": "e1", "source": "start", "target": "next"}])
    assert valid.status == GraphValidationStatus.VALID


def test_ai_rag_wait_same_node_allows_missing_edge() -> None:
    nodes = [
        {"id": "start", "type": "ai_rag", "data": {"isStart": True, "after_answer_behavior": "wait_same_node"}},
    ]

    result = FlowV2GraphValidator().validate(nodes=nodes, edges=[])
    assert result.status == GraphValidationStatus.VALID


def test_ai_rag_end_flow_allows_missing_edge() -> None:
    nodes = [
        {"id": "start", "type": "ai_rag", "data": {"isStart": True, "after_answer_behavior": "end_flow"}},
    ]

    result = FlowV2GraphValidator().validate(nodes=nodes, edges=[])
    assert result.status == GraphValidationStatus.VALID


def test_ai_agent_with_global_model_and_mcp_tools_publishes_safe_snapshot() -> None:
    nodes = [
        {"id": "start", "type": "message", "data": {"isStart": True, "content": "Olá"}},
        {
            "id": "agent",
            "type": "ai_agent",
            "data": {
                "instruction": "Use apenas ferramentas permitidas.",
                "input_template": "{{last_message}}",
                "allowed_tools": ["responder", "chamar_mcp"],
                "allow_mcp_tools": True,
                "mcp_tool_ids": ["tool-123"],
                "mcp_tools": [
                    {
                        "tool_id": "tool-123",
                        "tool_name": "consultar_pedido",
                        "server_id": "server-456",
                        "enabled": True,
                        "max_calls": 2,
                        "api_key": "must-not-be-snapshotted",
                        "headers": {"Authorization": "Bearer secret"},
                    }
                ],
                "model_override": "",
                "max_tokens": 1200,
                "max_mcp_calls": 2,
                "max_steps": 3,
                "after_answer_behavior": "end_flow",
            },
        },
    ]
    edges = [{"id": "e1", "source": "start", "target": "agent"}]

    result = FlowV2Publisher().publish(nodes=nodes, edges=edges)

    agent = _snapshot_node(result.snapshot, "agent")
    assert agent["data"]["max_tokens"] == 1200
    assert agent["data"]["mcp_tool_ids"] == ["tool-123"]
    assert agent["data"]["mcp_tools"] == [
        {
            "tool_id": "tool-123",
            "tool_name": "consultar_pedido",
            "server_id": "server-456",
            "enabled": True,
            "max_calls": 2,
        }
    ]
    serialized = str(agent["data"]).lower()
    assert "api_key" not in serialized
    assert "authorization" not in serialized
    assert "headers" not in serialized


def test_ai_agent_still_rejects_real_api_key() -> None:
    nodes = [
        {"id": "start", "type": "message", "data": {"isStart": True, "content": "Olá"}},
        {
            "id": "agent",
            "type": "ai_agent",
            "data": {
                "instruction": "Responda.",
                "allowed_tools": ["responder"],
                "max_steps": 3,
                "api_key": "sk-real-secret",
            },
        },
    ]
    edges = [{"id": "e1", "source": "start", "target": "agent"}]

    with pytest.raises(FlowV2PublishError) as exc:
        FlowV2Publisher().publish(nodes=nodes, edges=edges)

    assert "FLOW_V2_AI_NODE_API_KEY_FORBIDDEN:agent" in exc.value.errors


def _ai_system_node(system_id: str = "system") -> dict:
    return {
        "id": system_id,
        "type": "ai_system",
        "data": {
            "internal_nodes": [
                {"id": "dispatcher", "type": "ai_dispatcher", "data": {"isStart": True}},
                {"id": "greeting", "type": "ai_greeting", "data": {}},
                {"id": "calendar", "type": "ai_calendar_agent", "data": {}},
                {"id": "fallback", "type": "ai_safe_fallback", "data": {}},
            ],
            "internal_edges": [
                {"id": "i1", "source": "dispatcher", "target": "greeting", "sourceHandle": "default"},
                {"id": "i2", "source": "greeting", "target": "calendar", "sourceHandle": "default"},
                {"id": "i3", "source": "calendar", "target": "fallback", "sourceHandle": "default"},
            ],
        },
    }


def test_ai_system_publish_preserves_canvas_node_from_external_start() -> None:
    result = FlowV2Publisher().publish(
        nodes=[{"id": "start", "type": "start"}, _ai_system_node()],
        edges=[{"id": "e1", "source": "start", "target": "system"}],
    )

    assert [node["id"] for node in result.snapshot["nodes"]] == ["start", "system"]
    system = next(node for node in result.snapshot["nodes"] if node["id"] == "system")
    assert system["type"] == "ai_system"
    assert len(system["data"]["internal_nodes"]) == 4
    assert len(system["data"]["internal_edges"]) == 3
    assert result.snapshot["edges"] == [{"id": "e1", "source": "start", "target": "system"}]
    assert result.snapshot["start_node_id"] == "start"
    assert result.validation.status == GraphValidationStatus.VALID


def test_ai_system_publish_between_start_and_message_keeps_canvas_edges() -> None:
    result = FlowV2Publisher().publish(
        nodes=[{"id": "start", "type": "start"}, _ai_system_node(), {"id": "done", "type": "message", "data": {"content": "Fim"}}],
        edges=[
            {"id": "e1", "source": "start", "target": "system"},
            {"id": "e2", "source": "system", "target": "done"},
        ],
    )

    assert [edge["source"] for edge in result.snapshot["edges"]] == ["start", "system"]
    assert [edge["target"] for edge in result.snapshot["edges"]] == ["system", "done"]
    assert any(node["type"] == "ai_system" for node in result.snapshot["nodes"])
    assert len([node for node in result.snapshot["nodes"] if FlowV2GraphValidator._is_start_node(node)]) == 1


def test_ai_system_as_canvas_start_keeps_internal_graph_nested() -> None:
    system = _ai_system_node()
    system["data"]["isStart"] = True
    result = FlowV2Publisher().publish(nodes=[system], edges=[])

    assert result.snapshot["start_node_id"] == "system"
    assert len(result.snapshot["nodes"]) == 1
    assert result.snapshot["edges"] == []
    snapshot_system = result.snapshot["nodes"][0]
    assert snapshot_system["type"] == "ai_system"
    assert len(snapshot_system["data"]["internal_nodes"]) == 4
    assert len(snapshot_system["data"]["internal_edges"]) == 3


def test_ai_system_only_template_promotes_canvas_node_as_start_without_expanding() -> None:
    system = _ai_system_node()

    result = FlowV2Publisher().publish(nodes=[system], edges=[])

    assert result.validation.status == GraphValidationStatus.VALID
    assert result.snapshot["start_node_id"] == "system"
    assert len(result.snapshot["nodes"]) == 1
    assert result.snapshot["nodes"][0]["id"] == "system"
    assert result.snapshot["nodes"][0]["type"] == "ai_system"
    assert result.snapshot["edges"] == []


def test_ai_system_connected_to_other_nodes_does_not_create_duplicate_start() -> None:
    result = FlowV2Publisher().publish(
        nodes=[{"id": "start", "type": "start"}, _ai_system_node(), {"id": "done", "type": "message", "data": {"content": "Fim"}}],
        edges=[
            {"id": "e1", "source": "start", "target": "system"},
            {"id": "e2", "source": "system", "target": "done"},
        ],
    )

    start_ids = FlowV2GraphValidator._start_node_ids(result.snapshot["nodes"])
    assert start_ids == ["start"]
    assert result.snapshot["start_node_id"] == "start"
    assert not any(node["id"].endswith("__start") for node in result.snapshot["nodes"])


def test_ai_system_as_first_node_of_flow_uses_canvas_node_as_runtime_start() -> None:
    result = FlowV2Publisher().publish(
        nodes=[_ai_system_node(), {"id": "done", "type": "message", "data": {"content": "Fim"}}],
        edges=[{"id": "e1", "source": "system", "target": "done"}],
    )

    assert result.snapshot["start_node_id"] == "system"
    assert FlowV2GraphValidator._start_node_ids(result.snapshot["nodes"]) == ["system"]
    assert result.snapshot["edges"] == [{"id": "e1", "source": "system", "target": "done"}]


def test_multiple_independent_ai_systems_fail_exactly_one_start_validation_without_synthetic_starts() -> None:
    system_a = _ai_system_node("system_a")
    system_b = _ai_system_node("system_b")

    with pytest.raises(FlowV2PublishError) as exc:
        FlowV2Publisher().publish(nodes=[system_a, system_b], edges=[])

    assert "FLOW_V2_REQUIRES_EXACTLY_ONE_START_NODE" in exc.value.errors


def test_final_snapshot_contains_exactly_one_start_node_after_ai_system_preservation() -> None:
    result = FlowV2Publisher().publish(nodes=[_ai_system_node()], edges=[])

    start_ids = FlowV2GraphValidator._start_node_ids(result.snapshot["nodes"])
    assert start_ids == [result.snapshot["start_node_id"]]
    assert start_ids == ["system"]


def test_ai_system_serializer_keeps_ten_internal_edges_nested() -> None:
    system = _ai_system_node()
    system["data"]["internal_edges"] = [
        {"id": f"i{index}", "source": "dispatcher", "target": "greeting", "sourceHandle": f"h{index}"}
        for index in range(10)
    ]

    result = FlowV2Publisher().publish(nodes=[system], edges=[])

    assert len(result.snapshot["nodes"]) == 1
    assert len(result.snapshot["edges"]) == 0
    assert len(result.snapshot["nodes"][0]["data"]["internal_nodes"]) == 4
    assert len(result.snapshot["nodes"][0]["data"]["internal_edges"]) == 10
    assert not any("__" in str(edge.get("source")) or "__" in str(edge.get("target")) or str(edge.get("id", "")).startswith("system__") for edge in result.snapshot["edges"] if isinstance(edge, dict))


def test_legacy_start_to_ai_agent_still_publishes() -> None:
    result = FlowV2Publisher().publish(
        nodes=[
            {"id": "start", "type": "start"},
            {"id": "agent", "type": "ai_agent", "data": {"allowed_tools": ["responder"], "max_steps": 3}},
        ],
        edges=[{"id": "e1", "source": "start", "target": "agent"}],
    )

    assert result.validation.status == GraphValidationStatus.VALID
    assert any(node["id"] == "agent" and node["type"] == "ai_agent" for node in result.snapshot["nodes"])



def test_ai_system_publish_preserves_prefixed_internal_edges_from_camel_case_payload() -> None:
    system = _ai_system_node()
    system["data"]["internalNodes"] = system["data"].pop("internal_nodes")
    system["data"]["internalEdges"] = [
        {"id": "i1", "source": "system__dispatcher", "target": "system__greeting", "sourceHandle": "default"},
        {"id": "i2", "source": "system__dispatcher", "target": "system__calendar", "sourceHandle": "calendar"},
        {"id": "i3", "source": "system__dispatcher", "target": "system__fallback", "sourceHandle": "fallback"},
    ]
    system["data"].pop("internal_edges")

    result = FlowV2Publisher().publish(nodes=[system], edges=[])

    assert len(result.snapshot["nodes"]) == 1
    assert result.snapshot["nodes"][0]["type"] == "ai_system"
    assert result.snapshot["edges"] == []
    assert len(result.snapshot["nodes"][0]["data"]["internalNodes"]) == 4
    assert len(result.snapshot["nodes"][0]["data"]["internalEdges"]) == 3
    assert result.validation.status == GraphValidationStatus.VALID


def test_ai_system_internal_changes_affect_published_hash() -> None:
    system = _ai_system_node()
    first = FlowV2Publisher().publish(nodes=[{"id": "start", "type": "start"}, system], edges=[{"id": "e1", "source": "start", "target": "system"}])
    changed = _ai_system_node()
    changed["data"]["internal_nodes"][0]["data"]["prompt"] = "novo prompt"
    second = FlowV2Publisher().publish(nodes=[{"id": "start", "type": "start"}, changed], edges=[{"id": "e1", "source": "start", "target": "system"}])

    assert first.v2_snapshot_hash != second.v2_snapshot_hash


def test_ai_system_internal_edges_with_orphans_stay_nested_and_do_not_hit_canvas_validation() -> None:
    system = _ai_system_node()
    system["data"]["internal_edges"].append(
        {"id": "stale-target", "source": "fallback", "target": "deleted-node", "sourceHandle": "default"}
    )
    system["data"]["internal_edges"].append(
        {"id": "stale-source", "source": "deleted-node", "target": "fallback", "sourceHandle": "default"}
    )

    result = FlowV2Publisher().publish(nodes=[system], edges=[])

    assert result.validation.status == GraphValidationStatus.VALID
    assert result.snapshot["edges"] == []
    assert len(result.snapshot["nodes"][0]["data"]["internal_edges"]) == 5


def test_ai_system_rejects_internal_edge_leaked_to_canvas_edges() -> None:
    system = _ai_system_node()

    with pytest.raises(FlowV2PublishError) as exc:
        FlowV2Publisher().publish(
            nodes=[system],
            edges=[{"id": "system__i1", "source": "system__dispatcher", "target": "system__greeting"}],
        )

    assert "AI_SYSTEM_INTERNAL_EDGE_IN_CANVAS:system__i1" in exc.value.errors
