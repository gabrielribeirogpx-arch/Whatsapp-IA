"""Destructive Audit P0 proof, opt-in and restricted to disposable PostgreSQL."""
from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.models.tenant import Tenant
from app.services.audit_service import write_audit_log


def _staging_url() -> str:
    url = os.getenv("AUDIT_P0_POSTGRES_URL", "").strip()
    if not url:
        pytest.skip("AUDIT_P0_POSTGRES_URL not configured")
    assert url.startswith(("postgresql://", "postgresql+psycopg://", "postgresql+psycopg2://"))
    assert url != os.getenv("DATABASE_URL", ""), "refusing to target the application DATABASE_URL"
    lowered = url.lower()
    assert any(marker in lowered for marker in ("test", "staging", "temporary", "audit_p0")), "database name must identify a disposable test/staging database"
    return url


def test_real_postgresql_append_only_fk_and_application_insert():
    engine = create_engine(_staging_url())
    tenant_id = uuid.uuid4()
    audit_id: uuid.UUID

    # This is intentionally committed: later transactions prove database-level
    # protection, rather than SQLAlchemy's model listeners.
    with Session(engine) as db:
        tenant = Tenant(id=tenant_id, name="Audit P0 disposable proof", slug=f"audit-p0-{tenant_id}")
        db.add(tenant)
        db.flush()
        row = write_audit_log(db, action="audit_p0_postgresql_probe", tenant_id=tenant_id, entity_type="test", metadata={"source": "application"})
        db.commit()
        audit_id = row.id

    with engine.connect() as connection:
        assert connection.execute(text("SELECT action FROM audit_logs WHERE id=:id"), {"id": audit_id}).scalar_one() == "audit_p0_postgresql_probe"

    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(DBAPIError, match="append-only"):
            connection.execute(text("UPDATE audit_logs SET action='forbidden' WHERE id=:id"), {"id": audit_id})
        transaction.rollback()

    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(DBAPIError, match="append-only"):
            connection.execute(text("DELETE FROM audit_logs WHERE id=:id"), {"id": audit_id})
        transaction.rollback()

    with engine.connect() as connection:
        transaction = connection.begin()
        with pytest.raises(IntegrityError):
            connection.execute(text("DELETE FROM tenants WHERE id=:id"), {"id": tenant_id})
        transaction.rollback()

    with engine.connect() as connection:
        assert connection.execute(text("SELECT count(*) FROM audit_logs WHERE id=:id"), {"id": audit_id}).scalar_one() == 1
        assert connection.execute(text("SELECT count(*) FROM tenants WHERE id=:id"), {"id": tenant_id}).scalar_one() == 1
