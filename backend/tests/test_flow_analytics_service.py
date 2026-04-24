from __future__ import annotations

import unittest
import uuid

from app.services.flow_analytics_service import FLOW_FINISH, FLOW_SEND, FLOW_START, get_flow_analytics


class _FakeExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeDB:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, _stmt):
        return _FakeExecuteResult(self._rows)


class GetFlowAnalyticsTests(unittest.TestCase):
    def test_aggregates_known_event_types(self):
        db = _FakeDB(
            [
                (FLOW_START, 12),
                (FLOW_SEND, 48),
                (FLOW_FINISH, 9),
            ]
        )

        analytics = get_flow_analytics(db=db, tenant_id=uuid.uuid4(), flow_id=uuid.uuid4())

        self.assertEqual(analytics["entries"], 12)
        self.assertEqual(analytics["messages_sent"], 48)
        self.assertEqual(analytics["finalizations"], 9)

    def test_returns_zero_for_missing_event_types(self):
        db = _FakeDB([])

        analytics = get_flow_analytics(db=db, tenant_id=uuid.uuid4(), flow_id=uuid.uuid4())

        self.assertEqual(analytics, {"entries": 0, "messages_sent": 0, "finalizations": 0})


if __name__ == "__main__":
    unittest.main()
