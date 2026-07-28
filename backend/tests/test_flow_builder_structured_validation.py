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
