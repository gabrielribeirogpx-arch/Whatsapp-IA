from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.models.lead import Lead
from app.services import lead_auto_service


class _FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def first(self):
        return self.value


class _FakeExecuteResult:
    def __init__(self, value):
        self.value = value

    def scalars(self):
        return _FakeScalarResult(self.value)


class _FakeDB:
    def __init__(self, existing_lead=None):
        self.existing_lead = existing_lead
        self.added = []
        self.flushed = 0
        self.audit_rows = []

    def execute(self, statement):
        text = str(statement)
        if "FROM leads" in text:
            return _FakeExecuteResult(self.existing_lead)
        if "FROM tenant_users" in text:
            return _FakeExecuteResult(SimpleNamespace(id="owner-1"))
        if "FROM pipeline_stages" in text:
            return _FakeExecuteResult(None)
        return _FakeExecuteResult(None)

    def add(self, obj):
        self.added.append(obj)
        if getattr(obj, "action", None) == "LEAD_CREATED":
            self.audit_rows.append(obj)

    def flush(self):
        self.flushed += 1


def test_ensure_whatsapp_lead_for_inbound_creates_linked_lead_and_audit(monkeypatch, capsys):
    db = _FakeDB()
    stage = SimpleNamespace(id="stage-novo", name="Novo")
    contact = SimpleNamespace(id="contact-1", phone="+55 (11) 99999-0001", name="Cliente")
    conversation = SimpleNamespace(id="conversation-1")

    monkeypatch.setattr(lead_auto_service, "get_first_pipeline_stage", lambda _db, _tenant_id: stage)
    monkeypatch.setattr(lead_auto_service, "write_audit_log", lambda db, **kwargs: db.audit_rows.append(kwargs))

    result = lead_auto_service.ensure_whatsapp_lead_for_inbound(
        db,
        tenant_id="tenant-1",
        phone="+55 (11) 99999-0001",
        contact=contact,
        conversation=conversation,
        name="Cliente",
        message_text="Oi",
    )

    assert result is not None
    assert result.created is True
    assert result.lead in db.added
    assert result.lead.phone == "5511999990001"
    assert result.lead.source == "whatsapp"
    assert result.lead.score == 0
    assert result.lead.owner_id == "owner-1"
    assert result.lead.contact_id == "contact-1"
    assert result.lead.conversation_id == "conversation-1"
    assert result.lead.stage_id == "stage-novo"
    assert db.audit_rows[0]["action"] == "LEAD_CREATED"
    assert db.audit_rows[0]["metadata"]["automatic"] is True
    output = capsys.readouterr().out
    assert "[LEAD AUTO CREATED]" in output
    assert "[PIPELINE INSERT]" in output
    assert "[AUDIT LEAD CREATED]" in output


def test_ensure_whatsapp_lead_for_inbound_updates_existing_without_audit(monkeypatch):
    existing = Lead(tenant_id="tenant-1", phone="5511999990001", score=0)
    db = _FakeDB(existing_lead=existing)
    contact = SimpleNamespace(id="contact-1", phone="5511999990001", name="Cliente")
    conversation = SimpleNamespace(id="conversation-1")

    stage = SimpleNamespace(id="stage-novo", name="Novo")
    monkeypatch.setattr(lead_auto_service, "get_first_pipeline_stage", lambda _db, _tenant_id: stage)
    monkeypatch.setattr(lead_auto_service, "write_audit_log", lambda db, **kwargs: db.audit_rows.append(kwargs))

    result = lead_auto_service.ensure_whatsapp_lead_for_inbound(
        db,
        tenant_id="tenant-1",
        phone="5511999990001",
        contact=contact,
        conversation=conversation,
        name="Cliente",
        message_text="Nova mensagem",
    )

    assert result is not None
    assert result.created is False
    assert existing.contact_id == "contact-1"
    assert existing.conversation_id == "conversation-1"
    assert existing.last_message == "Nova mensagem"
    assert db.audit_rows == []


def test_ensure_whatsapp_lead_for_inbound_logs_new_conversation_activity(monkeypatch):
    db = _FakeDB()
    stage = SimpleNamespace(id="stage-novo", name="Novo")
    contact = SimpleNamespace(id="contact-1", phone="5511999990001", name="Cliente", email="c@example.com")
    conversation = SimpleNamespace(id="conversation-1")

    monkeypatch.setattr(lead_auto_service, "get_first_pipeline_stage", lambda _db, _tenant_id: stage)
    monkeypatch.setattr(lead_auto_service, "write_audit_log", lambda db, **kwargs: db.audit_rows.append(kwargs))

    result = lead_auto_service.ensure_whatsapp_lead_for_inbound(
        db,
        tenant_id="tenant-1",
        phone="5511999990001",
        contact=contact,
        conversation=conversation,
        name="Cliente",
        message_text="Oi",
        conversation_created=True,
    )

    assert result is not None
    assert result.lead.email == "c@example.com"
    assert [row["action"] for row in db.audit_rows] == ["LEAD_CREATED", "CONVERSATION_STARTED"]
    assert db.audit_rows[1]["metadata"]["event"] == "Nova conversa iniciada"
