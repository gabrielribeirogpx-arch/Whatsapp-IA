import os
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from datetime import datetime
from types import SimpleNamespace
from uuid import uuid4

from app.routers.chat import list_conversations


class _Result:
    def __init__(self, items):
        self._items = items

    def scalars(self):
        return self

    def all(self):
        return self._items

    def first(self):
        return self._items[0] if self._items else None


class FakeDB:
    def __init__(self, conversations, messages_by_conversation):
        self.conversations = conversations
        self.messages_by_conversation = messages_by_conversation

    def execute(self, stmt):
        sql = str(stmt)
        if "FROM conversations" in sql:
            tenant_id = stmt.compile().params.get("tenant_id_1")
            return _Result([c for c in self.conversations if str(c.tenant_id) == str(tenant_id)])
        if "FROM messages" in sql:
            conversation_id = stmt.compile().params.get("conversation_id_1")
            message = self.messages_by_conversation.get(str(conversation_id))
            return _Result([message] if message else [])
        return _Result([])


def test_tenant_sem_conversas_retorna_lista_vazia():
    tenant = SimpleNamespace(id=uuid4())
    payload = list_conversations(tenant=tenant, db=FakeDB([], {}))
    assert payload == []


def test_conversa_com_nulls_faz_fallbacks_e_isola_tenant():
    tenant_a = SimpleNamespace(id=uuid4())
    tenant_b = SimpleNamespace(id=uuid4())
    convo_a = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_a.id,
        contact_id=None,
        phone_number="5511999991111",
        name=None,
        avatar_url=None,
        mode=None,
        updated_at=datetime(2026, 1, 1),
        contact=None,
    )
    convo_b = SimpleNamespace(
        id=uuid4(),
        tenant_id=tenant_b.id,
        contact_id=None,
        phone_number="5511888882222",
        name="Outro",
        avatar_url=None,
        mode="human",
        updated_at=datetime(2026, 1, 2),
        contact=None,
    )
    payload = list_conversations(tenant=tenant_a, db=FakeDB([convo_a, convo_b], {}))

    assert len(payload) == 1
    item = payload[0]
    assert item.phone == "5511999991111"
    assert item.name == "5511999991111"
    assert item.last_message == ""
