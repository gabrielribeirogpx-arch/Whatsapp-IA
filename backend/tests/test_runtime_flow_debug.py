from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

from app.db.base import Base
from app.models.flow import Flow, FlowVersion
from app.models.tenant import Tenant
from app.models.tenant_whatsapp_provider import TenantWhatsAppProvider
from app.services.runtime_flow_diagnostics import (
    assert_flow_matches_whatsapp_tenant,
    build_runtime_flow_diagnostic,
)


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
        tables=[Tenant.__table__, Flow.__table__, FlowVersion.__table__, TenantWhatsAppProvider.__table__],
    )
    with Session(engine) as session:
        yield session


def _tenant(tenant_id: uuid.UUID, slug: str) -> Tenant:
    return Tenant(id=tenant_id, name=slug, slug=slug, admin_password="x")


def _active_flow(tenant_id: uuid.UUID, *, runtime: str = "v2") -> Flow:
    version_id = uuid.uuid4()
    flow = Flow(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        name="Runtime flow",
        is_active=True,
        is_deleted=False,
        trigger_type="default",
        priority=0,
        version=1,
        status="published",
        runtime=runtime,
        published_version_id=version_id,
    )
    return flow


def _provider(tenant_id: uuid.UUID, phone_number_id: str, *, active: bool = True) -> TenantWhatsAppProvider:
    return TenantWhatsAppProvider(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        provider_type="meta_cloud",
        phone_number_id=phone_number_id,
        is_active=active,
        status="connected" if active else "disconnected",
    )


def test_runtime_flow_diagnostic_match_true_when_builder_tenant_equals_webhook_tenant(db_session: Session):
    tenant_id = uuid.uuid4()
    flow = _active_flow(tenant_id, runtime="v2")
    db_session.add_all([_tenant(tenant_id, "builder"), _provider(tenant_id, "123"), flow])
    db_session.commit()

    diagnostic = build_runtime_flow_diagnostic(db_session, builder_tenant_id=tenant_id)

    assert diagnostic.as_dict() == {
        "builder_tenant": str(tenant_id),
        "webhook_tenant": str(tenant_id),
        "phone_number_id": "123",
        "active_flow_id": str(flow.id),
        "published_version_id": str(flow.published_version_id),
        "runtime": "v2",
        "match": True,
    }


def test_runtime_flow_diagnostic_match_false_when_builder_tenant_differs_from_webhook_tenant(db_session: Session):
    builder_tenant_id = uuid.uuid4()
    webhook_tenant_id = uuid.uuid4()
    webhook_flow = _active_flow(webhook_tenant_id, runtime="v1")
    db_session.add_all(
        [
            _tenant(builder_tenant_id, "builder"),
            _tenant(webhook_tenant_id, "webhook"),
            _provider(webhook_tenant_id, "456"),
            webhook_flow,
        ]
    )
    db_session.commit()

    diagnostic = build_runtime_flow_diagnostic(
        db_session,
        builder_tenant_id=builder_tenant_id,
        phone_number_id="456",
    )

    assert diagnostic.builder_tenant == str(builder_tenant_id)
    assert diagnostic.webhook_tenant == str(webhook_tenant_id)
    assert diagnostic.phone_number_id == "456"
    assert diagnostic.active_flow_id == str(webhook_flow.id)
    assert diagnostic.published_version_id == str(webhook_flow.published_version_id)
    assert diagnostic.runtime == "v1"
    assert diagnostic.match is False


def test_activation_guard_blocks_flow_when_whatsapp_number_resolves_to_other_tenant(db_session: Session):
    builder_tenant_id = uuid.uuid4()
    webhook_tenant_id = uuid.uuid4()
    flow = _active_flow(builder_tenant_id)
    db_session.add_all(
        [
            _tenant(builder_tenant_id, "builder"),
            _tenant(webhook_tenant_id, "webhook"),
            _provider(webhook_tenant_id, "789", active=True),
            flow,
        ]
    )
    builder_tenant = db_session.get(Tenant, builder_tenant_id)
    builder_tenant.phone_number_id = "789"
    db_session.commit()

    with pytest.raises(ValueError, match=f"tenant {builder_tenant_id}.*tenant {webhook_tenant_id}"):
        assert_flow_matches_whatsapp_tenant(db_session, flow=flow)
