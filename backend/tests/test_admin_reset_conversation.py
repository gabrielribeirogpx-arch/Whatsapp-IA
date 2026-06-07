from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from datetime import datetime, timedelta

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.db.base import Base
from app.flow_v2.models import FlowV2Event, FlowV2ScheduledJob, FlowV2Session
from app.models import (
    Contact,
    Conversation,
    ConversationLog,
    Flow,
    FlowEvent,
    FlowExecution,
    FlowExecutionEvent,
    FlowNode,
    FlowVersion,
    Lead,
    Message,
    PipelineStage,
    Tenant,
    TenantUser,
)
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

    @event.listens_for(engine, "connect")
    def _enable_sqlite_foreign_keys(dbapi_connection, _connection_record):
        dbapi_connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(
        engine,
        tables=[
            Tenant.__table__,
            Contact.__table__,
            Flow.__table__,
            FlowVersion.__table__,
            FlowNode.__table__,
            Conversation.__table__,
            Message.__table__,
            ConversationLog.__table__,
            FlowEvent.__table__,
            FlowExecution.__table__,
            FlowExecutionEvent.__table__,
            PipelineStage.__table__,
            Lead.__table__,
            TenantUser.__table__,
            FlowV2Session.__table__,
            FlowV2Event.__table__,
            FlowV2ScheduledJob.__table__,
        ],
    )
    with Session(engine) as session:
        yield session


def _create_first_message_runtime_state(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    contact_id: uuid.UUID,
    phone: str,
    flow_version_id: uuid.UUID,
    include_lead: bool = True,
):
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
    db.add(
        ConversationLog(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            message="Mensagem inicial",
            mode="bot",
            response="Resposta inicial",
        )
    )
    db.add(
        FlowEvent(
            tenant_id=tenant_id,
            conversation_id=conversation.id,
            flow_version_id=flow_version_id,
            event_type="node_entered",
            metadata_json={"node_id": "first-node"},
        )
    )
    execution = FlowExecution(
        tenant_id=tenant_id,
        contact_id=contact_id,
        conversation_id=conversation.id,
        flow_version_id=flow_version_id,
        user_phone=phone,
        status="running",
        current_node="first-node",
        completed=False,
        state={},
    )
    db.add(execution)
    db.flush()
    db.add(
        FlowExecutionEvent(
            execution_id=execution.id,
            node_id="first-node",
            event_type="node_entered",
        )
    )
    if include_lead:
        db.add(
            Lead(
                tenant_id=tenant_id,
                phone=phone,
                name="Cliente",
                contact_id=contact_id,
                conversation_id=conversation.id,
                last_message="Mensagem inicial",
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
    user = TenantUser(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        full_name="Admin",
        email="admin@example.com",
        password_hash="hash",
        role="admin",
    )
    flow = Flow(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="Fluxo",
        is_active=True,
        status="published",
        runtime="v2",
    )
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
    stale_version = FlowVersion(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        flow_id=flow.id,
        version=2,
        nodes=[{"id": "stale-node", "type": "message"}],
        edges=[],
        start_node_id="stale-node",
        is_active=False,
        is_published=False,
    )
    db_session.add(tenant)
    db_session.commit()
    db_session.add_all([contact, user, flow])
    db_session.commit()
    db_session.add_all([version, stale_version])
    db_session.commit()

    old_conversation, old_session = _create_first_message_runtime_state(
        db_session,
        tenant_id=tenant_id,
        contact_id=contact.id,
        phone=phone,
        flow_version_id=version.id,
    )

    stale_session = FlowV2Session(
        tenant_id=tenant_id,
        flow_version_id=stale_version.id,
        contact_id=contact.id,
        conversation_id=None,
        external_user_id=phone,
        status="completed",
        current_node_id="stale-node",
    )
    db_session.add(stale_session)
    db_session.flush()
    db_session.add(
        FlowV2Event(
            tenant_id=tenant_id,
            session_id=stale_session.id,
            flow_version_id=stale_version.id,
            event_index=1,
            event_type="NODE_ENTERED",
            node_id="stale-node",
            payload={},
        )
    )
    db_session.add(
        FlowV2ScheduledJob(
            tenant_id=tenant_id,
            session_id=stale_session.id,
            resume_node_id="stale-delay",
            run_at=datetime.utcnow() + timedelta(minutes=5),
        )
    )
    db_session.commit()

    old_conversation_id = old_conversation.id
    old_session_id = old_session.id
    stale_session_id = stale_session.id

    reset_result = reset_test_conversation(db_session, conversation=old_conversation)
    db_session.commit()

    assert reset_result.deleted_scheduled_jobs == 2
    assert reset_result.deleted_flow_events == 2
    assert reset_result.deleted_flow_sessions == 2
    assert reset_result.deleted_messages == 1
    assert reset_result.deleted_conversation_logs == 1
    assert reset_result.deleted_flow_events_v1 == 1
    assert reset_result.deleted_flow_execution_events == 1
    assert reset_result.deleted_flow_executions == 1
    assert reset_result.detached_leads == 1
    assert reset_result.deleted_conversations == 1
    assert db_session.get(Contact, contact.id) is not None
    assert db_session.get(Tenant, tenant_id) is not None
    assert db_session.get(TenantUser, user.id) is not None
    lead = db_session.execute(
        select(Lead).where(Lead.tenant_id == tenant_id, Lead.phone == phone)
    ).scalar_one()
    assert lead.conversation_id is None
    assert db_session.get(Conversation, old_conversation_id) is None
    assert db_session.get(FlowV2Session, old_session_id) is None
    assert db_session.get(FlowV2Session, stale_session_id) is None
    assert (
        db_session.execute(
            select(FlowV2Session).where(FlowV2Session.external_user_id == phone)
        )
        .scalars()
        .all()
        == []
    )
    assert (
        db_session.execute(
            select(Message).where(Message.conversation_id == old_conversation_id)
        )
        .scalars()
        .all()
        == []
    )
    assert (
        db_session.execute(
            select(ConversationLog).where(
                ConversationLog.conversation_id == old_conversation_id
            )
        )
        .scalars()
        .all()
        == []
    )
    assert (
        db_session.execute(
            select(FlowEvent).where(FlowEvent.conversation_id == old_conversation_id)
        )
        .scalars()
        .all()
        == []
    )
    assert (
        db_session.execute(
            select(FlowExecution).where(
                FlowExecution.conversation_id == old_conversation_id
            )
        )
        .scalars()
        .all()
        == []
    )

    new_conversation, new_session = _create_first_message_runtime_state(
        db_session,
        tenant_id=tenant_id,
        contact_id=contact.id,
        phone=phone,
        flow_version_id=version.id,
        include_lead=False,
    )

    assert new_conversation.id != old_conversation_id
    assert new_session.id != old_session_id
    assert new_session.current_node_id == first_node_id
    assert new_session.conversation_id == new_conversation.id
