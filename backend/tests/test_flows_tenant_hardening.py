from __future__ import annotations

import uuid

import pytest
from fastapi import HTTPException

from app.routers import flows


class _FakeFlow:
    def __init__(self, flow_id: uuid.UUID, tenant_id: uuid.UUID):
        self.id = flow_id
        self.tenant_id = tenant_id
        self.deleted_at = None


class _FakeQuery:
    def __init__(self, items):
        self.items = list(items)

    def filter(self, *conditions):
        # minimal evaluator for equality checks against Flow.tenant_id and deleted_at is None
        filtered = self.items
        for condition in conditions:
            text = str(condition)
            if "flows.tenant_id" in text and "=" in text:
                tenant_id = str(condition.right.value)
                filtered = [item for item in filtered if str(item.tenant_id) == tenant_id]
            if "flows.deleted_at IS NULL" in text:
                filtered = [item for item in filtered if item.deleted_at is None]
        return _FakeQuery(filtered)

    def first(self):
        return self.items[0] if self.items else None


def test_rejects_missing_tenant_header():
    with pytest.raises(HTTPException) as exc:
        flows._resolve_tenant_header(None)
    assert exc.value.status_code == 403


def test_rejects_invalid_tenant_header():
    with pytest.raises(HTTPException) as exc:
        flows._resolve_tenant_header("invalid")
    assert exc.value.status_code == 403


def test_cross_tenant_flow_lookup_is_blocked(monkeypatch):
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    flow = _FakeFlow(flow_id=uuid.uuid4(), tenant_id=tenant_b)

    monkeypatch.setattr(flows, "_resolve_flow_query", lambda db, flow_id: (_FakeQuery([flow]), flow.id))

    result = flows._get_flow_by_identifier(db=object(), flow_id=str(flow.id), tenant_id=tenant_a)
    assert result is None
