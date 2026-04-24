from __future__ import annotations

import unittest
import uuid
from datetime import datetime, timedelta

from app.models.flow import Flow
from app.services.flow_service import resolve_flow_for_message


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _ExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _ScalarResult(self._rows)


class _FakeDB:
    def __init__(self, flows):
        self._flows = flows

    def execute(self, _query):
        return _ExecuteResult(self._flows)


def _build_flow(
    *,
    name: str,
    trigger_type: str,
    trigger_value: str | None = None,
    is_active: bool = True,
    created_at: datetime | None = None,
) -> Flow:
    flow = Flow(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name=name,
        is_active=is_active,
        trigger_type=trigger_type,
        trigger_value=trigger_value,
        created_at=created_at or datetime.utcnow(),
        updated_at=created_at or datetime.utcnow(),
    )
    return flow


class ResolveFlowForMessageTests(unittest.TestCase):
    def test_keyword_routes_to_sales_flow(self):
        base_time = datetime.utcnow()
        sales = _build_flow(
            name="Vendas",
            trigger_type="keyword",
            trigger_value="vender, vendas, comercial",
            created_at=base_time,
        )
        default = _build_flow(
            name="Default",
            trigger_type="default",
            created_at=base_time + timedelta(seconds=1),
        )
        db = _FakeDB([sales, default])

        resolved = resolve_flow_for_message(db, tenant_id=uuid.uuid4(), message_text="Quero vender agora")

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.id, sales.id)

    def test_keyword_routes_to_integration_flow(self):
        base_time = datetime.utcnow()
        integration = _build_flow(
            name="Integração",
            trigger_type="keyword",
            trigger_value="api, integração",
            created_at=base_time,
        )
        default = _build_flow(
            name="Default",
            trigger_type="default",
            created_at=base_time + timedelta(seconds=1),
        )
        db = _FakeDB([integration, default])

        resolved = resolve_flow_for_message(db, tenant_id=uuid.uuid4(), message_text="api")

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.id, integration.id)

    def test_unknown_message_falls_back_to_default(self):
        base_time = datetime.utcnow()
        default = _build_flow(
            name="Default",
            trigger_type="default",
            created_at=base_time + timedelta(seconds=1),
        )
        api_only = _build_flow(
            name="API",
            trigger_type="keyword",
            trigger_value="api, integração",
            created_at=base_time,
        )
        db = _FakeDB([api_only, default])

        resolved = resolve_flow_for_message(db, tenant_id=uuid.uuid4(), message_text="mensagem desconhecida")

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.id, default.id)


if __name__ == "__main__":
    unittest.main()
