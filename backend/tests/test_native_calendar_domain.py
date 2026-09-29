import os
import uuid
from datetime import datetime, time
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import Session
from sqlalchemy.dialects.postgresql import JSONB, UUID

os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")

from app.db.base import Base
from app.models.contact import Contact
from app.models.native_calendar import (
    Appointment,
    AvailabilityRule,
    CalendarBlock,
    CalendarResource,
    NativeCalendar,
)
from app.models.tenant import Tenant
from app.services.native_calendar_service import NativeCalendarError, NativeCalendarService


@compiles(UUID, "sqlite")
def compile_uuid_for_sqlite(_type, _compiler, **_kwargs):
    return "CHAR(32)"


@compiles(JSONB, "sqlite")
def compile_jsonb_for_sqlite(_type, _compiler, **_kwargs):
    return "JSON"


TABLES = [
    Tenant.__table__,
    Contact.__table__,
    NativeCalendar.__table__,
    CalendarResource.__table__,
    AvailabilityRule.__table__,
    CalendarBlock.__table__,
    Appointment.__table__,
]


@pytest.fixture()
def db():
    engine = create_engine("sqlite+pysqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def enable_foreign_keys(connection, _record):
        connection.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine, tables=TABLES)
    with Session(engine) as session:
        yield session


def tenant(db, suffix="a"):
    row = Tenant(name=f"Tenant {suffix}", slug=f"tenant-{suffix}-{uuid.uuid4().hex[:8]}")
    db.add(row)
    db.flush()
    return row


def contact(db, owner, suffix="1"):
    row = Contact(tenant_id=owner.id, phone=f"55119999{suffix}{uuid.uuid4().hex[:4]}")
    db.add(row)
    db.flush()
    return row


def domain(db, owner):
    service = NativeCalendarService(db, tenant_id=owner.id)
    calendar = service.create_calendar(name="Agenda principal", timezone="America/Sao_Paulo")
    resource = service.create_resource(calendar_id=calendar.id, name="Sala 1", timezone="America/New_York")
    return service, calendar, resource


def instant(hour, minute=0, timezone_name="America/Sao_Paulo"):
    return datetime(2026, 10, 5, hour, minute, tzinfo=ZoneInfo(timezone_name))


def appointment_values(person, start=10, end=11, **overrides):
    values = {
        "contact_id": person.id,
        "start_at": instant(start),
        "end_at": instant(end),
        "timezone": "America/Sao_Paulo",
        "status": "scheduled",
        "source": "assistant",
        "service_reference": "consultation-v1",
    }
    values.update(overrides)
    return values


def test_creates_calendar_resource_and_local_availability_rule(db):
    owner = tenant(db)
    service, calendar, resource = domain(db, owner)
    rule = service.create_availability_rule(
        calendar_id=calendar.id,
        resource_id=resource.id,
        weekday=0,
        start_time=time(8),
        end_time=time(12),
    )
    assert calendar.tenant_id == owner.id
    assert calendar.timezone == "America/Sao_Paulo"
    assert resource.timezone == "America/New_York"
    assert (rule.weekday, rule.start_time, rule.end_time) == (0, time(8), time(12))


@pytest.mark.parametrize("start,end", [(time(8), time(8)), (time(9), time(8))])
def test_rejects_invalid_availability_range(start, end):
    with pytest.raises(ValueError, match="availability_start_must_precede_end"):
        AvailabilityRule(weekday=0, start_time=start, end_time=end)


def test_creates_block_and_normalizes_instants_to_utc(db):
    owner = tenant(db)
    service, calendar, resource = domain(db, owner)
    block = service.create_block(
        calendar_id=calendar.id, resource_id=resource.id,
        start_at=instant(12), end_at=instant(13), timezone="America/Sao_Paulo", reason="Manutenção",
    )
    assert block.start_at.utcoffset().total_seconds() == 0
    assert block.reason == "Manutenção"


def test_rejects_invalid_block_and_naive_instant():
    with pytest.raises(ValueError, match="start_must_precede_end"):
        CalendarBlock(start_at=instant(12), end_at=instant(11), timezone="America/Sao_Paulo")
    with pytest.raises(ValueError, match="timezone_aware"):
        CalendarBlock(start_at=datetime(2026, 1, 1, 10), end_at=instant(11), timezone="America/Sao_Paulo")


def test_creates_appointment_linked_to_canonical_contact(db):
    owner = tenant(db)
    person = contact(db, owner)
    service, calendar, resource = domain(db, owner)
    row = service.create_appointment(
        calendar_id=calendar.id, resource_id=resource.id, **appointment_values(person),
    )
    assert row.contact_id == person.id
    assert row.service_reference == "consultation-v1"
    assert not hasattr(row, "customer_name")


def test_rejects_invalid_appointment_range_status_source_and_timezone():
    common = {"start_at": instant(10), "end_at": instant(11), "timezone": "America/New_York"}
    with pytest.raises(ValueError, match="start_must_precede_end"):
        Appointment(start_at=instant(11), end_at=instant(10), timezone="America/Sao_Paulo")
    with pytest.raises(ValueError, match="invalid_appointment_status"):
        Appointment(**common, status="pending")
    with pytest.raises(ValueError, match="invalid_appointment_source"):
        Appointment(**common, source="llm")
    with pytest.raises(ValueError, match="invalid_timezone"):
        NativeCalendar(name="X", timezone="Mars/Olympus")


def test_allows_adjacent_appointments_and_rejects_overlap(db):
    owner = tenant(db)
    person = contact(db, owner)
    service, calendar, resource = domain(db, owner)
    service.create_appointment(calendar_id=calendar.id, resource_id=resource.id, **appointment_values(person, 10, 11))
    adjacent = service.create_appointment(calendar_id=calendar.id, resource_id=resource.id, **appointment_values(person, 11, 12))
    assert adjacent.id
    with pytest.raises(NativeCalendarError, match="appointment_conflict"):
        service.create_appointment(
            calendar_id=calendar.id, resource_id=resource.id,
            **appointment_values(person, start_at=instant(10, 30), end_at=instant(11, 30)),
        )


def test_cancelled_appointment_does_not_reserve_slot(db):
    owner = tenant(db)
    person = contact(db, owner)
    service, calendar, resource = domain(db, owner)
    service.create_appointment(
        calendar_id=calendar.id, resource_id=resource.id,
        **appointment_values(person, status="cancelled"),
    )
    active = service.create_appointment(
        calendar_id=calendar.id, resource_id=resource.id, **appointment_values(person),
    )
    assert active.status == "scheduled"


@pytest.mark.parametrize("relation", ["calendar_resource", "calendar_appointment", "resource_appointment", "contact_appointment"])
def test_cross_tenant_relations_fail_closed_at_database(db, relation):
    tenant_a = tenant(db, "a")
    tenant_b = tenant(db, "b")
    contact_a = contact(db, tenant_a, "a")
    contact_b = contact(db, tenant_b, "b")
    _, calendar_a, resource_a = domain(db, tenant_a)
    _, calendar_b, resource_b = domain(db, tenant_b)

    if relation == "calendar_resource":
        row = CalendarResource(tenant_id=tenant_a.id, calendar_id=calendar_b.id, name="Cross tenant")
    else:
        calendar_id = calendar_b.id if relation == "calendar_appointment" else calendar_a.id
        resource_id = resource_b.id if relation == "resource_appointment" else resource_a.id
        contact_id = contact_b.id if relation == "contact_appointment" else contact_a.id
        row = Appointment(
            tenant_id=tenant_a.id, calendar_id=calendar_id, resource_id=resource_id,
            contact_id=contact_id, start_at=instant(14), end_at=instant(15),
            timezone="America/Sao_Paulo", status="scheduled", source="api",
        )
    db.add(row)
    with pytest.raises(IntegrityError):
        db.flush()


def test_service_rejects_cross_tenant_identity_before_insert(db):
    tenant_a = tenant(db, "a")
    tenant_b = tenant(db, "b")
    contact_b = contact(db, tenant_b, "b")
    service_a, calendar_a, resource_a = domain(db, tenant_a)
    with pytest.raises(NativeCalendarError, match="contact_not_found"):
        service_a.create_appointment(
            calendar_id=calendar_a.id, resource_id=resource_a.id, **appointment_values(contact_b),
        )


def test_migration_declares_postgresql_half_open_exclusion_and_reversible_tables():
    migration = Path(__file__).parents[1] / "alembic/versions/20260929_native_calendar_domain.py"
    text = migration.read_text()
    assert 'tstzrange(start_at, end_at, \'[)\') WITH &&' in text
    assert "WHERE (status <> 'cancelled')" in text
    assert "CREATE EXTENSION IF NOT EXISTS btree_gist" in text
    assert 'down_revision = "20260928_template_cert"' in text
    for table in ("appointments", "calendar_blocks", "availability_rules", "calendar_resources", "native_calendars"):
        assert f'op.drop_table("{table}")' in text
