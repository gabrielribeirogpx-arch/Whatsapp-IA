from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.db.base import Base
from app.models import AuditLog, Plan, PlanFeature, Subscription, Tenant, TenantEntitlement, TenantUser, UserSession
from app.routers import auth
from app.services.trial_service import TRIAL_PLAN_CODE


@compiles(PG_UUID, "sqlite")
def _compile_pg_uuid_sqlite(_type, _compiler, **_kw):
    return "CHAR(32)"


@compiles(JSONB, "sqlite")
def _compile_jsonb_sqlite(_type, _compiler, **_kw):
    return "JSON"


@pytest.fixture()
def register_client(monkeypatch):
    engine = create_engine("sqlite+pysqlite://", future=True, connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine, tables=[Tenant.__table__, TenantUser.__table__, UserSession.__table__, Plan.__table__, PlanFeature.__table__, Subscription.__table__, TenantEntitlement.__table__, AuditLog.__table__])
    with Session(engine) as session:
        plan = Plan(code=TRIAL_PLAN_CODE, name="Growth Trial", is_active=True, is_public=False, monthly_price_cents=0, annual_price_cents=0)
        session.add(plan)
        session.flush()
        session.add(PlanFeature(plan_id=plan.id, feature_key="flows", enabled=True))
        session.commit()

    app = FastAPI()
    app.include_router(auth.router, prefix="/api")

    def override_get_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(auth, "enforce_rate_limit", lambda **_kwargs: None)
    monkeypatch.setattr(auth, "validate_turnstile_or_raise", lambda **_kwargs: None)
    return TestClient(app, raise_server_exceptions=False), engine


def _payload() -> dict[str, str]:
    return {"full_name": "Novo Usuário", "email": "novo@example.com", "password": "Senha@123", "confirm_password": "Senha@123", "business_name": "Empresa Nova", "whatsapp_number": "5511999999999", "business_segment": "Varejo", "intended_use": "Atender clientes"}


def test_register_creates_complete_trial_without_500(register_client):
    client, engine = register_client

    response = client.post("/api/register", json=_payload())

    assert response.status_code == 200
    with Session(engine) as session:
        tenant = session.query(Tenant).one()
        subscription = session.query(Subscription).filter_by(tenant_id=tenant.id).one()
        audit = session.query(AuditLog).filter_by(tenant_id=tenant.id, action="TRIAL_STARTED").one()
        assert session.query(TenantUser).filter_by(tenant_id=tenant.id).count() == 1
        assert subscription.plan_id == session.query(Plan.id).filter_by(code=TRIAL_PLAN_CODE).scalar()
        assert subscription.status == "trialing"
        assert subscription.trial_ends_at - subscription.trial_started_at == timedelta(days=14)
        assert audit.metadata_json["trial_ends_at"] == subscription.trial_ends_at.isoformat()


def test_register_rolls_back_all_records_when_audit_persistence_fails(register_client, monkeypatch):
    client, engine = register_client
    monkeypatch.setattr(auth, "write_audit_log", lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("audit failed")))

    response = client.post("/api/register", json=_payload())

    assert response.status_code == 500
    with Session(engine) as session:
        assert session.query(Tenant).count() == 0
        assert session.query(TenantUser).count() == 0
        assert session.query(Subscription).count() == 0
        assert session.query(TenantEntitlement).count() == 0
        assert session.query(AuditLog).count() == 0
