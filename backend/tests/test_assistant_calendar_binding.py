import os
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, event, select
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.db.base import Base
from app.models.audit_log import AuditLog
from app.models.integration_connection import IntegrationConnection
from app.models.marketplace_installation import AssistantCalendarBinding, MarketplaceInstallation, MarketplaceInstallationResource
from app.models.native_calendar import AvailabilityRule, CalendarResource, NativeCalendar
from app.models.tenant import Tenant
from app.models.tenant_appointment_policy import TenantAppointmentPolicy
from app.models.user import TenantUser
from app.schemas.assistant_configuration import AssistantConfigurationV1
from app.services.assistant_calendar_binding_service import bind_assistant_calendar


@compiles(UUID, "sqlite")
def _uuid_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


@compiles(JSONB, "sqlite")
def _json_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


TABLES = [Tenant.__table__, TenantUser.__table__, TenantAppointmentPolicy.__table__, IntegrationConnection.__table__,
          MarketplaceInstallation.__table__, MarketplaceInstallationResource.__table__,
          NativeCalendar.__table__, CalendarResource.__table__, AvailabilityRule.__table__,
          AssistantCalendarBinding.__table__, AuditLog.__table__]


@pytest.fixture()
def state():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    @event.listens_for(engine, "connect")
    def _fk(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine, tables=TABLES)
    with Session(engine) as db:
        tenant = Tenant(name="Clínica", slug=f"clinic-{uuid.uuid4().hex}")
        other_tenant = Tenant(name="Outra", slug=f"other-{uuid.uuid4().hex}")
        db.add_all([tenant, other_tenant])
        db.flush()
        user = TenantUser(tenant_id=tenant.id, full_name="Admin", email=f"{uuid.uuid4()}@test.local",
                          password_hash="x", role="owner", status="active")
        db.add(user)
        db.flush()
        installation = MarketplaceInstallation(
            tenant_id=tenant.id, template_id="agenda", template_slug="agenda_inteligente",
            template_type="assistant", template_version="1", automation_level="full_ai", variant="default",
            status="completed", idempotency_key=uuid.uuid4().hex, installed_by_user_id=user.id,
            manifest_snapshot={"capabilities": ["appointment_assistant_configuration"]},
        )
        db.add(installation)
        db.flush()
        yield db, tenant, other_tenant, user, installation


def native_config():
    return AssistantConfigurationV1.model_validate({
        "schema_version": 1, "clinic_name": "Clínica Vida",
        "services": [{"id": "consulta", "label": "Consulta", "duration_minutes": 30}],
        "calendar": {"provider": "wazza_native", "timezone": "America/Sao_Paulo",
                     "resource_name": "Dra. Ana",
                     "business_hours": {"monday": [{"start": "08:00", "end": "12:00"}]}},
        "handoff": {"enabled": False},
    })


def google_config(connection_id):
    return AssistantConfigurationV1.model_validate({
        "schema_version": 1, "clinic_name": "Clínica Vida",
        "services": [{"id": "consulta", "label": "Consulta", "duration_minutes": 30}],
        "google_calendar_connection_id": str(connection_id),
        "calendar": {"provider": "google_calendar"},
        "handoff": {"enabled": False},
    })


def test_native_binding_provisions_once_and_replaces_rules_idempotently(state):
    db, tenant, other, user, installation = state
    first = bind_assistant_calendar(db, installation=installation, configuration=native_config(),
                                    actor_id=user.id, request=None)
    db.flush()
    calendar_id, resource_id = first.native_calendar_id, first.native_resource_id
    second = bind_assistant_calendar(db, installation=installation, configuration=native_config(),
                                     actor_id=user.id, request=None)
    db.flush()
    assert second.id == first.id
    assert (second.native_calendar_id, second.native_resource_id) == (calendar_id, resource_id)
    assert db.scalars(select(NativeCalendar)).all().__len__() == 1
    assert db.scalars(select(CalendarResource)).all().__len__() == 1
    assert [(rule.weekday, str(rule.start_time), str(rule.end_time)) for rule in db.scalars(select(AvailabilityRule))] == [(0, "08:00:00", "12:00:00")]


def test_switching_providers_preserves_inactive_provider_data(state):
    db, tenant, other, user, installation = state
    native = bind_assistant_calendar(db, installation=installation, configuration=native_config(),
                                     actor_id=user.id, request=None)
    native_ids = native.native_calendar_id, native.native_resource_id
    connection = IntegrationConnection(tenant_id=tenant.id, provider="google_calendar", auth_type="oauth2", status="active")
    db.add(connection)
    db.flush()
    google = bind_assistant_calendar(db, installation=installation, configuration=google_config(connection.id),
                                     actor_id=user.id, request=None)
    assert google.provider == "google_calendar" and google.integration_connection_id == connection.id
    assert google.native_calendar_id is None and google.native_resource_id is None
    assert db.get(IntegrationConnection, connection.id) is connection
    assert db.get(NativeCalendar, native_ids[0]) is not None
    restored = bind_assistant_calendar(db, installation=installation, configuration=native_config(),
                                       actor_id=user.id, request=None)
    assert (restored.native_calendar_id, restored.native_resource_id) == native_ids


def test_google_binding_rejects_cross_tenant_connection(state):
    db, tenant, other, user, installation = state
    connection = IntegrationConnection(tenant_id=other.id, provider="google_calendar", auth_type="oauth2", status="active")
    db.add(connection)
    db.flush()
    with pytest.raises(HTTPException) as error:
        bind_assistant_calendar(db, installation=installation, configuration=google_config(connection.id),
                                actor_id=user.id, request=None)
    assert error.value.detail == "invalid_google_calendar_connection"


def test_legacy_google_configuration_remains_valid_and_explicit_binding_wins():
    connection_id = uuid.uuid4()
    legacy = google_config(connection_id).model_copy(update={"calendar": None})
    assert legacy.effective_calendar_provider == "google_calendar"
    with pytest.raises(Exception):
        AssistantConfigurationV1.model_validate({
            **legacy.model_dump(),
            "calendar": {"provider": "wazza_native", "timezone": "UTC", "business_hours": {}},
        })


def test_database_rejects_hybrid_binding(state):
    db, tenant, other, user, installation = state
    row = AssistantCalendarBinding(
        tenant_id=tenant.id, installation_id=installation.id, provider="google_calendar",
        integration_connection_id=uuid.uuid4(), native_calendar_id=uuid.uuid4(),
    )
    db.add(row)
    with pytest.raises(IntegrityError):
        db.flush()


def test_binding_migration_is_non_destructive_and_follows_native_calendar_head():
    migration = Path(__file__).parents[1] / "alembic/versions/20260930_assistant_calendar_binding.py"
    text = migration.read_text()
    assert 'down_revision = "20260929_native_calendar"' in text
    assert 'op.create_table(\n        "assistant_calendar_bindings"' in text
    assert "google_calendar_connection_id" not in text
    assert "DROP" not in text.split("def downgrade", 1)[0].upper()
