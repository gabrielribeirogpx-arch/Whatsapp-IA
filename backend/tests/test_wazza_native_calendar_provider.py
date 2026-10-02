import os
import uuid
from datetime import datetime, time
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.db.base import Base
from app.models.audit_log import AuditLog
from app.models.contact import Contact
from app.models.native_calendar import Appointment, AvailabilityRule, CalendarBlock, CalendarResource, NativeCalendar
from app.models.tenant import Tenant
from app.models.user import TenantUser
from app.services.calendar_provider import CalendarProvider
from app.services.calendar_provider_resolver import CalendarProviderResolver
from app.services.native_calendar_service import NativeCalendarService
from app.services.wazza_native_calendar_provider import WazzaNativeCalendarProvider
from app.tools.context import ToolContext
from app.tools.adapters.google_calendar_tool_adapter import GoogleCalendarToolAdapter


@compiles(UUID, "sqlite")
def _uuid_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


@compiles(JSONB, "sqlite")
def _json_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


TABLES = [Tenant.__table__, TenantUser.__table__, Contact.__table__, NativeCalendar.__table__, CalendarResource.__table__,
          AvailabilityRule.__table__, CalendarBlock.__table__, Appointment.__table__, AuditLog.__table__]


@pytest.fixture()
def setup():
    engine = create_engine("sqlite+pysqlite:///:memory:")
    @event.listens_for(engine, "connect")
    def _foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")
    Base.metadata.create_all(engine, tables=TABLES)
    with Session(engine) as db:
        tenant = Tenant(name="Tenant", slug=f"tenant-{uuid.uuid4().hex}")
        db.add(tenant)
        db.flush()
        contact = Contact(tenant_id=tenant.id, phone="5511" + uuid.uuid4().hex[:10])
        other = Contact(tenant_id=tenant.id, phone="5522" + uuid.uuid4().hex[:10])
        db.add_all([contact, other])
        db.flush()
        service = NativeCalendarService(db, tenant_id=tenant.id)
        calendar = service.create_calendar(name="Agenda", timezone="America/Sao_Paulo")
        resource = service.create_resource(calendar_id=calendar.id, name="Profissional")
        provider = WazzaNativeCalendarProvider(db, tenant.id, contact.id, calendar.id, resource.id)
        yield db, tenant, contact, other, service, calendar, resource, provider


def dt(day, hour, tz="America/Sao_Paulo"):
    return datetime(2026, 10, day, hour, tzinfo=ZoneInfo(tz)).isoformat()


def rule(service, calendar, resource, weekday=0, start=8, end=18):
    return service.create_availability_rule(calendar_id=calendar.id, resource_id=resource.id,
                                            weekday=weekday, start_time=time(start), end_time=time(end))


def test_no_rule_has_no_availability_and_rule_generates_period_and_exact_slots(setup):
    db, tenant, contact, other, service, calendar, resource, provider = setup
    result = provider.check_availability(start=dt(5, 8), end=dt(5, 10), mode="period", _effective_duration_minutes=30)
    assert result == {"ok": True, "busy": [], "appointments": []}
    rule(service, calendar, resource)
    period = provider.check_availability(start=dt(5, 8), end=dt(5, 10), mode="period", _effective_duration_minutes=30)
    exact = provider.check_availability(start=dt(5, 9), end=dt(5, 9).replace("09:00", "09:30"),
                                        mode="exact", _effective_duration_minutes=30)
    assert len(period["appointments"]) == 2
    assert len(exact["appointments"]) == 1


def test_blocks_active_appointments_and_cancelled_status_control_busy_slots(setup):
    db, tenant, contact, other, service, calendar, resource, provider = setup
    rule(service, calendar, resource)
    service.create_block(calendar_id=calendar.id, resource_id=resource.id,
                         start_at=datetime.fromisoformat(dt(5, 9)), end_at=datetime.fromisoformat(dt(5, 10)),
                         timezone=calendar.timezone)
    active = service.create_appointment(calendar_id=calendar.id, resource_id=resource.id, contact_id=contact.id,
        start_at=datetime.fromisoformat(dt(5, 10)), end_at=datetime.fromisoformat(dt(5, 11)),
        timezone=calendar.timezone, status="scheduled", source="assistant")
    cancelled = service.create_appointment(calendar_id=calendar.id, resource_id=resource.id, contact_id=contact.id,
        start_at=datetime.fromisoformat(dt(5, 11)), end_at=datetime.fromisoformat(dt(5, 12)),
        timezone=calendar.timezone, status="cancelled", source="assistant")
    result = provider.check_availability(start=dt(5, 9), end=dt(5, 12), _effective_duration_minutes=60)
    assert [slot["start"][11:16] for slot in result["appointments"]] == ["11:00"]
    assert active.status == "scheduled" and cancelled.status == "cancelled"


def test_create_find_reschedule_cancel_list_and_audit(setup):
    db, tenant, contact, other, service, calendar, resource, provider = setup
    rule(service, calendar, resource)
    created = provider.create_event(start=dt(5, 10), end=dt(5, 11), service_reference="consultation")
    found = provider.find_managed_appointments(start=dt(5, 8), end=dt(5, 18), timezone=None,
                                                patient_ref="ignored", metadata_schema="ignored")
    updated = provider.update_event(created["event_id"], start=dt(5, 12), end=dt(5, 13))
    listed = provider.list_events(start=dt(5, 8), end=dt(5, 18))
    cancelled = provider.delete_event(created["event_id"])
    assert created["ok"] and len(found["appointments"]) == 1
    assert updated["start"][11:16] == "15:00"  # persisted instant is UTC
    assert len(listed["events"]) == 1 and cancelled["deleted"]
    assert [row.action for row in db.scalars(__import__("sqlalchemy").select(AuditLog).order_by(AuditLog.created_at))] == [
        "appointment.created", "appointment.rescheduled", "appointment.cancelled"
    ]
    assert provider.check_availability(start=dt(5, 12), end=dt(5, 13), mode="exact",
                                       _effective_duration_minutes=60)["appointments"]


def test_conflict_adjacency_ownership_and_isolation(setup):
    db, tenant, contact, other, service, calendar, resource, provider = setup
    rule(service, calendar, resource)
    first = provider.create_event(start=dt(5, 10), end=dt(5, 11))
    assert provider.create_event(start=dt(5, 10), end=dt(5, 11))["message"] == "slot_conflict"
    assert provider.create_event(start=dt(5, 11), end=dt(5, 12))["ok"]
    outsider = WazzaNativeCalendarProvider(db, tenant.id, other.id, calendar.id, resource.id)
    assert outsider.update_event(first["id"], start=dt(5, 13), end=dt(5, 14))["message"] == "appointment_not_found"
    assert outsider.list_events(start=dt(5, 8), end=dt(5, 18))["events"] == []
    assert WazzaNativeCalendarProvider(db, uuid.uuid4(), contact.id, calendar.id, resource.id).check_availability(
        start=dt(5, 8), end=dt(5, 9))["message"] == "calendar_not_found"


@pytest.mark.parametrize(("calendar_active", "resource_active", "code"), [
    (False, True, "calendar_inactive"), (True, False, "resource_inactive")])
def test_inactive_binding_and_invalid_period(setup, calendar_active, resource_active, code):
    db, tenant, contact, other, service, calendar, resource, provider = setup
    calendar.active, resource.active = calendar_active, resource_active
    assert provider.check_availability(start=dt(5, 8), end=dt(5, 9))["message"] == code
    calendar.active = resource.active = True
    assert provider.check_availability(start=dt(5, 9), end=dt(5, 8))["message"] == "invalid_period"


@pytest.mark.parametrize(("timezone_name", "day", "weekday"), [
    ("America/Sao_Paulo", 5, 0), ("America/New_York", 5, 0), ("America/New_York", 1, 6)])
def test_civil_timezone_and_new_york_dst(setup, timezone_name, day, weekday):
    db, tenant, contact, other, service, calendar, resource, provider = setup
    calendar.timezone, resource.timezone = timezone_name, timezone_name
    # Nov 1 2026 is New York's fall DST transition; a civil 09:00 rule remains 09:00.
    rule(service, calendar, resource, weekday=weekday, start=9, end=11)
    start = datetime(2026, 11 if day == 1 else 10, day, 9, tzinfo=ZoneInfo(timezone_name))
    result = provider.check_availability(start=start.isoformat(), end=start.replace(hour=11).isoformat(),
                                         _effective_duration_minutes=60)
    assert result["appointments"][0]["start"][11:16] == "09:00"


def test_resolver_returns_protocol_native_provider_from_server_binding(setup):
    db, tenant, contact, other, service, calendar, resource, provider = setup
    resolved = CalendarProviderResolver(db).resolve(ToolContext(
        tenant_id=tenant.id, contact_id=contact.id, calendar_provider="wazza_native",
        native_calendar_id=calendar.id, native_resource_id=resource.id,
    ))
    assert isinstance(resolved, WazzaNativeCalendarProvider)
    assert isinstance(resolved, CalendarProvider)


def test_historical_google_availability_tool_uses_trusted_native_binding(setup, monkeypatch):
    db, tenant, contact, other, service, calendar, resource, provider = setup
    rule(service, calendar, resource)
    monkeypatch.setattr(
        "app.services.appointment_duration_service.resolve_effective_appointment_duration",
        lambda *_args, **_kwargs: type("Duration", (), {
            "source": "assistant_configuration", "service_id": "consulta", "duration_minutes": 30,
        })(),
    )
    monkeypatch.setattr(
        "app.services.appointment_policy_service.policy_for_tenant",
        lambda *_args, **_kwargs: {"default_duration_minutes": 60},
    )

    result = GoogleCalendarToolAdapter(db).execute(
        "google_calendar_check_availability",
        {"start": dt(5, 8), "end": dt(5, 9), "timezone": "America/Sao_Paulo"},
        ToolContext(
            tenant_id=tenant.id, contact_id=contact.id,
            calendar_provider="wazza_native", native_calendar_id=calendar.id,
            native_resource_id=resource.id,
            runtime_variables={"appointment_type": "consulta"},
        ),
    )

    assert result.ok is True
    assert result.output["appointments"][0]["end"].endswith("08:30:00-03:00")
