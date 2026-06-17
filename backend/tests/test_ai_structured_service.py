import uuid

import pytest

from app.services import ai_structured_service as svc


def test_classify_returns_valid_category(monkeypatch):
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: '{"category":"vendas","confidence":0.91,"reason":"pedido"}')
    result = svc.classify_for_tenant(None, uuid.uuid4(), "quero comprar", ["vendas", "suporte"])
    assert result["category"] == "vendas"
    assert result["confidence"] == 0.91


def test_classify_uses_other_below_threshold(monkeypatch):
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: '{"category":"vendas","confidence":0.2,"reason":"incerto"}')
    result = svc.classify_for_tenant(None, uuid.uuid4(), "oi", ["vendas", "suporte"], options={"confidence_threshold": 0.6})
    assert result["category"] == "outro"


def test_classify_blocks_category_outside_list(monkeypatch):
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: '{"category":"hack","confidence":0.99,"reason":"x"}')
    result = svc.classify_for_tenant(None, uuid.uuid4(), "x", ["vendas", "suporte"])
    assert result["category"] == "outro"


def test_extract_returns_fields_and_missing(monkeypatch):
    monkeypatch.setattr(svc, "generate_answer_for_tenant", lambda *a, **k: '{"data":{"nome":"Gabriel","data":null},"missing_fields":["data"],"confidence":0.82}')
    result = svc.extract_for_tenant(None, uuid.uuid4(), "Gabriel", [{"name": "nome", "type": "string"}, {"name": "data", "type": "date"}])
    assert result["data"]["nome"] == "Gabriel"
    assert result["data"]["data"] is None
    assert "data" in result["missing_fields"]


def test_parse_removes_json_fence():
    assert svc._parse_json_only('```json\n{"ok": true}\n```') == {"ok": True}
