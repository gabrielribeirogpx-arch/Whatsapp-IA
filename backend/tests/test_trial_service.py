from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timedelta
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
from app.models.audit_log import AuditLog
from app.models.billing import Plan, PlanFeature, Subscription, TenantEntitlement
from app.models.tenant import Tenant
from app.models.user import TenantUser
from app.services.trial_service import TRIAL_PLAN_CODE, TrialService


@compiles(PG_UUID, "sqlite")
def _compile_pg_uuid_sqlite(_type, _compiler, **_kw):
    return "CHAR(32)"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:", future=True)
    Base.metadata.create_all(engine, tables=[Tenant.__table__, TenantUser.__table__, Plan.__table__, PlanFeature.__table__, Subscription.__table__, TenantEntitlement.__table__, AuditLog.__table__])
    with Session(engine) as session:
        plan = Plan(code=TRIAL_PLAN_CODE, name="Growth Trial", is_active=True, is_public=False, monthly_price_cents=0, annual_price_cents=0)
        session.add(plan)
        session.flush()
        session.add(PlanFeature(plan_id=plan.id, feature_key="flows", enabled=True))
        session.commit()
        yield session


def make_tenant(db: Session) -> Tenant:
    tenant = Tenant(id=uuid.uuid4(), name="Trial tenant", slug=f"trial-{uuid.uuid4().hex}", admin_password="x")
    db.add(tenant)
    db.commit()
    return tenant


def test_start_trial_creates_fourteen_day_growth_subscription_and_entitlements(db: Session):
    tenant = make_tenant(db)
    started = datetime(2026, 7, 21, 10)
    trial = TrialService(db).start_trial(tenant.id, now=started)

    assert trial.status == "trialing"
    assert trial.trial_ends_at == started + timedelta(days=14)
    assert TrialService(db).days_remaining(tenant.id, now=started) == 14
    assert db.query(TenantEntitlement).filter_by(tenant_id=tenant.id, source="trial").count() == 1
    audit = db.query(AuditLog).filter_by(tenant_id=tenant.id, action="TRIAL_STARTED").one()
    assert audit.metadata_json == {"trial_ends_at": (started + timedelta(days=14)).isoformat(), "days": 14}


def test_extend_and_expire_trial_are_isolated_per_tenant(db: Session):
    first, second = make_tenant(db), make_tenant(db)
    service = TrialService(db)
    started = datetime(2026, 7, 1)
    service.start_trial(first.id, now=started)
    service.start_trial(second.id, now=started)
    service.extend_trial(first.id, 3, now=started)
    service.expire_due_trials(now=started + timedelta(days=15))

    assert service._subscription(first.id).status == "trialing"
    assert service._subscription(second.id).status == "expired"
    assert db.query(AuditLog).filter_by(tenant_id=first.id, action="TRIAL_EXTENDED").count() == 1
    assert db.query(AuditLog).filter_by(tenant_id=second.id, action="TRIAL_EXPIRED").count() == 1
