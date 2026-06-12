from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models import AuditLog, Contact, Conversation, Lead, PipelineStage, Tenant, TenantUser
from app.models.lead import LeadStatus
from app.services import lead_auto_service
from app.services.lead_auto_service import create_or_update_lead_from_flow_action
from app.services.lead_service import soft_delete_lead_by_phone


@compiles(PG_UUID, "sqlite")
def _compile_pg_uuid_sqlite(_type, _compiler, **_kw):
    return "CHAR(32)"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(
        engine,
        tables=[
            Tenant.__table__,
            Contact.__table__,
            Conversation.__table__,
            PipelineStage.__table__,
            Lead.__table__,
            TenantUser.__table__,
            AuditLog.__table__,
        ],
    )
    with Session(engine) as session:
        yield session


def _seed_lead(
    db: Session, *, tenant_id: uuid.UUID, phone: str
) -> tuple[Lead, Contact, Conversation]:
    contact = Contact(tenant_id=tenant_id, phone=phone, name="Contato Teste")
    stage = PipelineStage(tenant_id=tenant_id, name=f"Novo {tenant_id.hex[:6]}", position=0)
    db.add_all([contact, stage])
    db.flush()
    conversation = Conversation(
        tenant_id=tenant_id,
        contact_id=contact.id,
        phone_number=phone,
        name="Contato Teste",
    )
    db.add(conversation)
    db.flush()
    lead = Lead(
        tenant_id=tenant_id,
        phone=phone,
        name="Lead Teste",
        stage_id=stage.id,
        status=LeadStatus.ACTIVE.value,
        contact_id=contact.id,
        conversation_id=conversation.id,
    )
    db.add(lead)
    db.flush()
    return lead, contact, conversation


def test_soft_delete_lead_by_phone_is_tenant_scoped_and_preserves_contact_conversation(
    db_session: Session,
):
    phone = "5511999990001"
    tenant_id = uuid.uuid4()
    other_tenant_id = uuid.uuid4()
    db_session.add_all(
        [
            Tenant(id=tenant_id, name="Tenant A", slug="tenant-a"),
            Tenant(id=other_tenant_id, name="Tenant B", slug="tenant-b"),
        ]
    )
    db_session.flush()
    lead, contact, conversation = _seed_lead(db_session, tenant_id=tenant_id, phone=phone)
    other_lead, _, _ = _seed_lead(db_session, tenant_id=other_tenant_id, phone=phone)

    result = soft_delete_lead_by_phone(
        db_session, tenant_id=tenant_id, phone="+55 (11) 99999-0001"
    )
    db_session.commit()

    assert result is not None
    assert result.lead.id == lead.id
    assert result.contact and result.contact.id == contact.id
    assert result.conversation and result.conversation.id == conversation.id
    assert db_session.get(Contact, contact.id) is not None
    assert db_session.get(Conversation, conversation.id) is not None
    assert db_session.get(Lead, lead.id).status == LeadStatus.DELETED.value
    assert db_session.get(Lead, other_lead.id).status == LeadStatus.ACTIVE.value
    assert (
        db_session.execute(
            select(Lead).where(
                Lead.tenant_id == tenant_id,
                Lead.status != LeadStatus.DELETED.value,
            )
        )
        .scalars()
        .all()
        == []
    )


def test_flow_create_lead_reactivates_soft_deleted_lead_for_same_tenant(
    db_session: Session,
    monkeypatch,
):
    phone = "5511999990002"
    tenant_id = uuid.uuid4()
    db_session.add(Tenant(id=tenant_id, name="Tenant A", slug="tenant-a"))
    db_session.flush()
    lead, contact, conversation = _seed_lead(db_session, tenant_id=tenant_id, phone=phone)
    original_lead_id = lead.id

    assert (
        soft_delete_lead_by_phone(db_session, tenant_id=tenant_id, phone=phone)
        is not None
    )
    db_session.commit()

    monkeypatch.setattr(lead_auto_service, "sync_publish", lambda *_args, **_kwargs: None)
    result = create_or_update_lead_from_flow_action(
        db_session,
        tenant_id=tenant_id,
        phone=phone,
        contact_id=contact.id,
        conversation_id=conversation.id,
        lead_name="Lead Recriado",
        last_message="Criar Lead pelo Flow Builder",
    )
    db_session.commit()

    assert result is not None
    assert result.created is False
    assert result.lead.id == original_lead_id
    assert result.lead.status == LeadStatus.ACTIVE.value
    assert result.lead.name == "Lead Recriado"
    assert result.lead.contact_id == contact.id
    assert result.lead.conversation_id == conversation.id
