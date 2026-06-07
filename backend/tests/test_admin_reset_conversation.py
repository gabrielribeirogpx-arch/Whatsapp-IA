from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.db.base import Base
from app.flow_v2.models import FlowV2Event, FlowV2ScheduledJob, FlowV2Session
from app.models import Contact, Conversation, Flow, FlowVersion, Message, Tenant
from app.services.admin_conversation_reset_service import reset_test_conversation


@compiles(PG_UUID, "sqlite")
def _compile_pg_uuid_sqlite(_type, _compiler, **_kw):
    return "CHAR(32)"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(
        engine,
        tables=[
            Tenant.__table__,
            Contact.__table__,
            Flow.__table__,
            FlowVersion.__table__,
            Conversation.__table__,
            Message.__table__,
            FlowV2Session.__table__,
            FlowV2Event.__table__,
            FlowV2ScheduledJob.__table__,
        ],
    )
    with Session(engine) as session:
        yield session


def _create_first_message_runtime_state(db: Session, *, tenant_id: uuid.UUID, contact_id: uuid.UUID, phone: str, flow_version_id: uuid.UUID):
    conversation = Conversation(
        tenant_id=tenant_id,
        contact_id=contact_id,
        phone_number=phone,
        mode="bot",
    )
    db.add(conversation)
    db.flush()

    message = Message(
        tenant_id=tenant_id,
        conversation_id=conversation.id,
        text="Mensagem inicial",
        from_me=False,
    )
    db.add(message)

    session = FlowV2Session(
        tenant_id=tenant_id,
        flow_version_id=flow_version_id,
        contact_id=contact_id,
        conversation_id=conversation.id,
        external_user_id=phone,
        status="waiting",
        current_node_id="first-node",
    )
    db.add(session)
    db.flush()

    db.add(
        FlowV2Event(
            tenant_id=tenant_id,
            session_id=session.id,
            flow_version_id=flow_version_id,
            event_index=1,
            event_type="NODE_ENTERED",
            node_id="first-node",
            payload={"message_id": str(message.id)},
        )
    )
    db.add(
        FlowV2ScheduledJob(
            tenant_id=tenant_id,
            session_id=session.id,
            resume_node_id="after-delay",
            run_at=datetime.utcnow() + timedelta(minutes=5),
        )
    )
    db.commit()
    return conversation, session


def test_message_flow_reset_new_message_restarts_from_first_node(db_session: Session):
    tenant_id = uuid.uuid4()
    phone = "5511999990001"
    first_node_id = "first-node"

    tenant = Tenant(id=tenant_id, name="Tenant", slug="tenant", admin_password="x")
    contact = Contact(id=uuid.uuid4(), tenant_id=tenant_id, phone=phone, name="Cliente")
    flow = Flow(id=uuid.uuid4(), tenant_id=tenant_id, name="Fluxo", is_active=True, status="published", runtime="v2")
    version = FlowVersion(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        flow_id=flow.id,
        version=1,
        nodes=[{"id": first_node_id, "type": "message"}],
        edges=[],
        start_node_id=first_node_id,
        is_active=True,
        is_published=True,
    )
    db_session.add_all([tenant, contact, flow, version])
    db_session.commit()

    old_conversation, old_session = _create_first_message_runtime_state(
        db_session,
        tenant_id=tenant_id,
        contact_id=contact.id,
        phone=phone,
        flow_version_id=version.id,
    )

    old_conversation_id = old_conversation.id
    old_session_id = old_session.id

    reset_result = reset_test_conversation(db_session, conversation=old_conversation)
    db_session.commit()

    assert reset_result.deleted_scheduled_jobs == 1
    assert reset_result.deleted_flow_sessions == 1
    assert reset_result.deleted_messages == 1
    assert reset_result.deleted_conversations == 1
    assert db_session.get(Contact, contact.id) is not None
    assert db_session.get(Conversation, old_conversation_id) is None
    assert db_session.get(FlowV2Session, old_session_id) is None
    assert db_session.execute(select(FlowV2Session).where(FlowV2Session.external_user_id == phone)).scalars().all() == []

    new_conversation, new_session = _create_first_message_runtime_state(
        db_session,
        tenant_id=tenant_id,
        contact_id=contact.id,
        phone=phone,
        flow_version_id=version.id,
    )

    assert new_conversation.id != old_conversation_id
    assert new_session.id != old_session_id
    assert new_session.current_node_id == first_node_id
    assert new_session.conversation_id == new_conversation.id
