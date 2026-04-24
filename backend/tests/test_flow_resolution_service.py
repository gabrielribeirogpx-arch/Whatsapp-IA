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


class _ConversationStub:
    def __init__(self, *, mode: str, conversation_id: uuid.UUID | None = None):
        self.mode = mode
        self.id = conversation_id or uuid.uuid4()


def _build_flow(
    *,
    name: str,
    trigger_type: str,
    trigger_value: str | None = None,
    keywords: str | None = None,
    stop_words: str | None = None,
    priority: int = 0,
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
        keywords=keywords,
        stop_words=stop_words,
        priority=priority,
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

    def test_priority_and_keyword_scoring_prefers_highest_score(self):
        base_time = datetime.utcnow()
        flow_a = _build_flow(
            name="Automação",
            trigger_type="keyword",
            keywords="automatizar, bot",
            priority=5,
            created_at=base_time,
        )
        flow_b = _build_flow(
            name="Vendas",
            trigger_type="keyword",
            keywords="vendas",
            priority=1,
            created_at=base_time + timedelta(seconds=1),
        )
        default = _build_flow(
            name="Default",
            trigger_type="default",
            created_at=base_time + timedelta(seconds=2),
        )
        db = _FakeDB([flow_a, flow_b, default])

        resolved = resolve_flow_for_message(db, tenant_id=uuid.uuid4(), message_text="quero automatizar vendas")

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.id, flow_a.id)

    def test_legacy_trigger_value_used_when_keywords_is_empty(self):
        base_time = datetime.utcnow()
        legacy_flow = _build_flow(
            name="Legacy",
            trigger_type="keyword",
            trigger_value="integracao, api",
            created_at=base_time,
        )
        default = _build_flow(
            name="Default",
            trigger_type="default",
            created_at=base_time + timedelta(seconds=1),
        )
        db = _FakeDB([legacy_flow, default])

        resolved = resolve_flow_for_message(db, tenant_id=uuid.uuid4(), message_text="preciso de API")

        self.assertIsNotNone(resolved)
        self.assertEqual(resolved.id, legacy_flow.id)

    def test_does_not_recalculate_when_conversation_is_already_flow_mode(self):
        base_time = datetime.utcnow()
        keyword_flow = _build_flow(
            name="Keyword",
            trigger_type="keyword",
            keywords="vendas",
            created_at=base_time,
        )
        db = _FakeDB([keyword_flow])
        conversation = _ConversationStub(mode="flow")

        resolved = resolve_flow_for_message(
            db,
            tenant_id=uuid.uuid4(),
            message_text="quero vendas",
            conversation=conversation,
        )

        self.assertIsNone(resolved)


if __name__ == "__main__":
    unittest.main()
