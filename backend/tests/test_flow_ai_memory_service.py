from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.services.flow_ai_memory_service import FlowAIMemoryService


class _Result:
    def __init__(self, values=None):
        self.values = values or []

    def scalars(self):
        return self

    def all(self):
        return self.values

    def first(self):
        return self.values[0] if self.values else None


class _DB:
    def __init__(self, existing=None):
        self.added = []
        self.existing = existing or []

    def add(self, row):
        self.added.append(row)

    def flush(self):
        pass

    def execute(self, statement):
        text = str(statement)
        if "flow_ai_conversation_messages" in text:
            return _Result(self.existing)
        return _Result([])


def test_ai_memory_appends_user_and_assistant_messages():
    service = FlowAIMemoryService()
    db = _DB()
    tenant_id = uuid.uuid4()
    flow_id = uuid.uuid4()
    session_id = uuid.uuid4()
    node_id = uuid.uuid4()

    service.append_user_message(db, tenant_id=tenant_id, flow_id=flow_id, flow_version_id=None, session_id=session_id, conversation_id=None, contact_id=None, node_id=node_id, content="Oi", metadata={"message_id": "m1"})
    service.append_assistant_message(db, tenant_id=tenant_id, flow_id=flow_id, flow_version_id=None, session_id=session_id, conversation_id=None, contact_id=None, node_id=node_id, content="Olá", metadata=None)

    assert [row.role for row in db.added] == ["user", "assistant"]
    assert db.added[0].metadata_json["external_message_id"] == "m1"


def test_ai_memory_recent_history_ordered_and_limited():
    service = FlowAIMemoryService()
    now = datetime.utcnow()
    rows = [
        SimpleNamespace(role="user", content="um", created_at=now, id=uuid.uuid4()),
        SimpleNamespace(role="assistant", content="dois", created_at=now + timedelta(seconds=1), id=uuid.uuid4()),
        SimpleNamespace(role="user", content="tres", created_at=now + timedelta(seconds=2), id=uuid.uuid4()),
    ]
    db = _DB(existing=list(reversed(rows)))

    history = service.get_recent_history(db, tenant_id=uuid.uuid4(), session_id=uuid.uuid4(), max_messages=2, max_chars=20)

    assert [message.content for message in history] == ["dois", "tres"]
    assert service.build_history_for_prompt(history) == "Assistente: dois\nUsuário: tres"


def test_ai_memory_deduplicates_external_message_id():
    service = FlowAIMemoryService()
    existing = SimpleNamespace(role="user", content="Oi")
    db = _DB(existing=[existing])

    result = service.append_user_message(db, tenant_id=uuid.uuid4(), flow_id=uuid.uuid4(), flow_version_id=None, session_id=uuid.uuid4(), conversation_id=None, contact_id=None, node_id=uuid.uuid4(), content="Oi", metadata={"external_message_id": "m1"})

    assert result is existing
    assert db.added == []
