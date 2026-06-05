from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.flow import Flow
from app.services.flow_activation_service import activate_flow_exclusively
from app.services.flow_runtime_selector import resolve_runtime_flow_for_conversation


@compiles(PG_UUID, "sqlite")
def _compile_pg_uuid_sqlite(_type, _compiler, **_kw):
    return "CHAR(32)"


@pytest.fixture()
def db_session():
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[Flow.__table__])
    with Session(engine) as session:
        yield session


def _flow(tenant_id: uuid.UUID, name: str) -> Flow:
    return Flow(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name=name,
        description=None,
        is_active=False,
        is_deleted=False,
        trigger_type="default",
        trigger_value=None,
        priority=0,
        version=1,
        status="published",
        runtime="v2",
        published_version_id=uuid.uuid4(),
    )


def _active_ids(session: Session, tenant_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        session.execute(
            select(Flow.id)
            .where(Flow.tenant_id == tenant_id, Flow.is_active.is_(True))
            .order_by(Flow.name.asc())
        ).scalars()
    )


def test_successive_activation_keeps_one_active_flow_per_tenant(db_session: Session):
    tenant_id = uuid.uuid4()
    flows = [_flow(tenant_id, "A"), _flow(tenant_id, "B"), _flow(tenant_id, "C")]
    db_session.add_all(flows)
    db_session.commit()

    activate_flow_exclusively(db=db_session, tenant_id=tenant_id, flow=flows[0])
    db_session.commit()
    assert _active_ids(db_session, tenant_id) == [flows[0].id]

    activate_flow_exclusively(db=db_session, tenant_id=tenant_id, flow=flows[1])
    db_session.commit()
    assert _active_ids(db_session, tenant_id) == [flows[1].id]

    activate_flow_exclusively(db=db_session, tenant_id=tenant_id, flow=flows[2])
    db_session.commit()
    assert _active_ids(db_session, tenant_id) == [flows[2].id]


def test_activation_is_scoped_to_tenant(db_session: Session):
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    flow_a1 = _flow(tenant_a, "A1")
    flow_a2 = _flow(tenant_a, "A2")
    flow_b1 = _flow(tenant_b, "B1")
    db_session.add_all([flow_a1, flow_a2, flow_b1])
    db_session.commit()

    activate_flow_exclusively(db=db_session, tenant_id=tenant_a, flow=flow_a1)
    activate_flow_exclusively(db=db_session, tenant_id=tenant_b, flow=flow_b1)
    db_session.commit()

    activate_flow_exclusively(db=db_session, tenant_id=tenant_a, flow=flow_a2)
    db_session.commit()

    assert _active_ids(db_session, tenant_a) == [flow_a2.id]
    assert _active_ids(db_session, tenant_b) == [flow_b1.id]


def test_runtime_selector_logs_and_rejects_multiple_active_flows(monkeypatch, caplog):
    tenant_id = uuid.uuid4()
    first = _flow(tenant_id, "A")
    second = _flow(tenant_id, "B")
    first.is_active = True
    second.is_active = True

    class ScalarResult:
        def all(self):
            return [first, second]

        def first(self):
            return None

    class ExecuteResult:
        def scalars(self):
            return ScalarResult()

    class DB:
        def execute(self, *_args, **_kwargs):
            return ExecuteResult()

    conversation = type("Conversation", (), {"current_flow_id": None, "current_flow": None})()

    with caplog.at_level("ERROR"):
        with pytest.raises(RuntimeError, match="Multiple active flows"):
            resolve_runtime_flow_for_conversation(db=DB(), tenant_id=tenant_id, conversation=conversation, message_text="oi")

    assert "[MULTIPLE_ACTIVE_FLOWS]" in caplog.text
