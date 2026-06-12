from __future__ import annotations

import os
from types import SimpleNamespace

from sqlalchemy.exc import IntegrityError

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
    assert "[LEAD CREATED]" in output
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




class _FakeDBWithDuplicate(_FakeDB):
    def __init__(self, recovered_lead):
        super().__init__(existing_lead=None)
        self.recovered_lead = recovered_lead
        self.lead_queries = 0
        self.rolled_back = False

    def execute(self, statement):
        text = str(statement)
        if "FROM leads" in text:
            self.lead_queries += 1
            if self.lead_queries >= 3:
                return _FakeExecuteResult(self.recovered_lead)
            return _FakeExecuteResult(None)
        return super().execute(statement)

    def flush(self):
        self.flushed += 1
        if self.flushed == 1:
            raise IntegrityError("insert leads", {}, Exception("duplicate key value violates unique constraint"))


def test_ensure_whatsapp_lead_for_inbound_recovers_duplicate_insert(monkeypatch, capsys):
    recovered = Lead(tenant_id="tenant-1", phone="5511999990001", score=0)
    db = _FakeDBWithDuplicate(recovered)
    stage = SimpleNamespace(id="stage-novo", name="Novo")
    contact = SimpleNamespace(id="contact-1", phone="5511999990001", name="Cliente")
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
        message_text="Oi de novo",
    )

    assert result is not None
    assert result.created is False
    assert result.lead is recovered
    assert recovered.contact_id == "contact-1"
    assert recovered.conversation_id == "conversation-1"
    assert recovered.last_message == "Oi de novo"
    assert db.audit_rows == []
    output = capsys.readouterr().out
    assert "[LEAD DUPLICATE RECOVERED]" in output
    assert "[FLOW CONTINUING AFTER LEAD RECOVERY]" in output


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


def test_create_or_update_lead_from_flow_action_creates_linked_lead_with_audit_and_realtime(monkeypatch):
    db = _FakeDB()
    stage = SimpleNamespace(id="stage-novo", name="Novo")
    contact = SimpleNamespace(
        id="contact-1",
        tenant_id="tenant-1",
        phone="5511999990001",
        name="Contato Fallback",
        email="c@example.com",
    )
    conversation = SimpleNamespace(id="conversation-1", tenant_id="tenant-1", phone_number="5511999990001")
    published = []

    def fake_execute(statement):
        text = str(statement)
        if "FROM contacts" in text:
            return _FakeExecuteResult(contact)
        if "FROM conversations" in text:
            return _FakeExecuteResult(conversation)
        return _FakeDB.execute(db, statement)

    db.execute = fake_execute
    monkeypatch.setattr(lead_auto_service, "get_first_pipeline_stage", lambda _db, _tenant_id: stage)
    monkeypatch.setattr(lead_auto_service, "write_audit_log", lambda db, **kwargs: db.audit_rows.append(kwargs))
    monkeypatch.setattr(lead_auto_service, "sync_publish", lambda channel, payload: published.append((channel, payload)))

    result = lead_auto_service.create_or_update_lead_from_flow_action(
        db,
        tenant_id="tenant-1",
        phone="+55 (11) 99999-0001",
        contact_id="contact-1",
        conversation_id="conversation-1",
        lead_name="Lead Param",
        last_message="Mensagem do runtime",
        metadata={"contact_name": "Metadata Nome"},
    )

    assert result is not None
    assert result.created is True
    assert result.lead.phone == "5511999990001"
    assert result.lead.name == "Lead Param"
    assert result.lead.contact_id == "contact-1"
    assert result.lead.conversation_id == "conversation-1"
    assert result.lead.last_message == "Mensagem do runtime"
    assert [row["action"] for row in db.audit_rows] == ["LEAD_CREATED", "FLOW_LEAD_CREATED"]
    assert db.audit_rows[-1]["metadata"]["event"] == "Lead criado automaticamente pelo Flow Builder."
    assert published[0][0] == "dashboard:tenant-1"
    assert published[0][1]["event"] == "lead_created"


def test_create_or_update_lead_from_flow_action_updates_existing_without_duplicate_and_metadata_name(monkeypatch):
    existing = Lead(tenant_id="tenant-1", phone="5511999990001", name="5511999990001", score=0)
    db = _FakeDB(existing_lead=existing)
    contact = SimpleNamespace(
        id="contact-1", tenant_id="tenant-1", phone="5511999990001", name="Contato Fallback"
    )
    conversation = SimpleNamespace(id="conversation-1", tenant_id="tenant-1", phone_number="5511999990001")
    published = []

    def fake_execute(statement):
        text = str(statement)
        if "FROM contacts" in text:
            return _FakeExecuteResult(contact)
        if "FROM conversations" in text:
            return _FakeExecuteResult(conversation)
        return _FakeDB.execute(db, statement)

    db.execute = fake_execute
    monkeypatch.setattr(
        lead_auto_service,
        "get_first_pipeline_stage",
        lambda _db, _tenant_id: SimpleNamespace(id="stage-novo", name="Novo"),
    )
    monkeypatch.setattr(lead_auto_service, "write_audit_log", lambda db, **kwargs: db.audit_rows.append(kwargs))
    monkeypatch.setattr(lead_auto_service, "sync_publish", lambda channel, payload: published.append((channel, payload)))

    result = lead_auto_service.create_or_update_lead_from_flow_action(
        db,
        tenant_id="tenant-1",
        phone="5511999990001",
        contact_id="contact-1",
        conversation_id="conversation-1",
        last_message="Nova mensagem",
        metadata={"contact_name": "Nome Metadata"},
    )

    assert result is not None
    assert result.created is False
    assert result.lead is existing
    assert db.added == []
    assert existing.name == "Nome Metadata"
    assert existing.contact_id == "contact-1"
    assert existing.conversation_id == "conversation-1"
    assert existing.last_message == "Nova mensagem"
    assert [row["action"] for row in db.audit_rows] == ["FLOW_LEAD_UPDATED"]
    assert db.audit_rows[0]["metadata"]["event"] == "Lead atualizado automaticamente pelo Flow Builder."
    assert published[0][1]["event"] == "lead_updated"


def test_create_or_update_lead_from_flow_action_uses_contact_name_fallback(monkeypatch):
    db = _FakeDB()
    contact = SimpleNamespace(
        id="contact-1", tenant_id="tenant-1", phone="5511999990001", name="Nome Contato", email=None
    )

    def fake_execute(statement):
        text = str(statement)
        if "FROM contacts" in text:
            return _FakeExecuteResult(contact)
        if "FROM conversations" in text:
            return _FakeExecuteResult(None)
        return _FakeDB.execute(db, statement)

    db.execute = fake_execute
    monkeypatch.setattr(lead_auto_service, "get_first_pipeline_stage", lambda _db, _tenant_id: None)
    monkeypatch.setattr(lead_auto_service, "write_audit_log", lambda db, **kwargs: db.audit_rows.append(kwargs))
    monkeypatch.setattr(lead_auto_service, "sync_publish", lambda channel, payload: None)

    result = lead_auto_service.create_or_update_lead_from_flow_action(
        db,
        tenant_id="tenant-1",
        phone="5511999990001",
        contact_id="contact-1",
    )

    assert result is not None
    assert result.lead.name == "Nome Contato"


def test_create_or_update_lead_from_flow_action_skips_missing_phone(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(lead_auto_service, "write_audit_log", lambda db, **kwargs: db.audit_rows.append(kwargs))
    monkeypatch.setattr(lead_auto_service, "sync_publish", lambda channel, payload: None)

    result = lead_auto_service.create_or_update_lead_from_flow_action(db, tenant_id="tenant-1", phone="")

    assert result is None
    assert db.added == []
    assert db.audit_rows == []
