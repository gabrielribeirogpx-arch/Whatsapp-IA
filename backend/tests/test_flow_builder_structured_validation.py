import os
os.environ.setdefault('DATABASE_URL', 'sqlite+pysqlite:///:memory:')

from fastapi import HTTPException
import pytest

from app.routers.flows import validate_flow_payload_or_400
from app.services.flow_validation import validate_builder_graph


def test_condition_empty_has_friendly_node_context_and_multiple_errors():
    nodes = [
        {"id": "condition-1", "type": "condition", "data": {"isStart": True, "label": "Verificar interesse", "conditions": []}},
        {"id": "message-1", "type": "message", "data": {"label": "Encerramento", "content": "", "isEnd": True}},
    ]
    issues = validate_builder_graph(nodes, [])
    condition = next(issue for issue in issues if issue["code"] == "CONDITION_EMPTY")
    assert condition["node_id"] == "condition-1"
    assert condition["node_label"] == "Verificar interesse"
    assert condition["message"] == "Adicione pelo menos uma regra."
    assert condition["focus_field"] == "conditions"
    assert len(issues) > 1


def test_message_requires_output_has_node_id_and_no_code_only_message():
    nodes = [{"id": "message-1", "type": "message", "data": {"isStart": True, "content": "Olá"}}]
    issue = next(item for item in validate_builder_graph(nodes, []) if item["code"] == "MESSAGE_REQUIRES_OUTPUT")
    assert issue["node_id"] == "message-1"
    assert issue["message"] == "Conecte esta mensagem a outro node ou marque-a como fim do fluxo."
    assert issue["message"] != issue["code"]


def test_http_contract_keeps_legacy_detail_but_primary_errors_are_structured():
    with pytest.raises(HTTPException) as caught:
        validate_flow_payload_or_400(
            [{"id": "condition-1", "type": "condition", "data": {"isStart": True, "conditions": []}}],
            [],
        )
    detail = caught.value.detail
    assert detail["success"] is False
    assert detail["error"]["code"] == "CONDITION_EMPTY"
    assert detail["errors"]
    assert detail["legacy_detail"] == "VALIDATION_ERROR: CONDITION_EMPTY"


def test_data_collection_retry_validation_adapts_to_exhausted_behavior():
    base_data = {
        "isStart": True,
        "variable_name": "email",
        "data_type": "email",
        "max_attempts": 3,
        "timeout_seconds": 0,
        "cancel_keywords": [],
        "auto_retry_invalid": True,
    }
    success_edge = {"source": "collection-1", "target": "end-1", "sourceHandle": "success"}
    end_node = {"id": "end-1", "type": "message", "data": {"content": "Fim", "isEnd": True}}

    end_issues = validate_builder_graph(
        [{"id": "collection-1", "type": "data_collection", "data": {**base_data, "attempts_exceeded_behavior": "end"}}, end_node],
        [success_edge],
    )
    assert not any(issue["field"] == "connections" and "Tentativas esgotadas" in issue["message"] for issue in end_issues)

    follow_issues = validate_builder_graph(
        [{"id": "collection-1", "type": "data_collection", "data": {**base_data, "attempts_exceeded_behavior": "invalid"}}, end_node],
        [success_edge],
    )
    assert not any(issue["field"] == "connections" for issue in follow_issues)

    connected_issues = validate_builder_graph(
        [{"id": "collection-1", "type": "data_collection", "data": {**base_data, "attempts_exceeded_behavior": "invalid"}}, end_node],
        [success_edge, {"source": "collection-1", "target": "end-1", "sourceHandle": "invalid"}],
    )
    assert not any(issue["field"] == "connections" and "Tentativas esgotadas" in issue["message"] for issue in connected_issues)


@pytest.mark.parametrize("handle", ["success", "error", "timeout", "default", "selected", "custom-option"])
def test_reachability_traverses_every_handle_from_mcp_and_dynamic_choice(handle):
    nodes = [
        {"id": "start", "type": "message", "data": {"isStart": True, "content": "Início"}},
        {"id": "tool", "type": "mcp_tool", "data": {}},
        {"id": "dynamic", "type": "choice_dynamic", "data": {"options_mode": "dynamic"}},
        {"id": "end", "type": "message", "data": {"content": "Fim", "isEnd": True}},
    ]
    edges = [
        {"source": "start", "target": "tool", "sourceHandle": "default"},
        {"source": "tool", "target": "dynamic", "sourceHandle": handle},
        {"source": "dynamic", "target": "end", "sourceHandle": "selected"},
    ]

    issues = validate_builder_graph(nodes, edges)

    assert not [issue for issue in issues if issue["code"] == "NODE_ORPHAN"]
