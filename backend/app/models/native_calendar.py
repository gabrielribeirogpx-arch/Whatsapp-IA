from __future__ import annotations

import uuid
from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.db.base import Base


APPOINTMENT_STATUSES = frozenset({"scheduled", "cancelled", "completed"})
APPOINTMENT_SOURCES = frozenset({"assistant", "manual", "api"})


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_timezone(value: str) -> str:
    candidate = str(value or "").strip()
    try:
        ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("invalid_timezone") from exc
    return candidate


def _validate_instant(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime_must_be_timezone_aware")
    return value.astimezone(timezone.utc)


class NativeCalendar(Base):
    __tablename__ = "native_calendars"
    __table_args__ = (
        CheckConstraint("length(trim(name)) > 0", name="ck_native_calendars_name_not_blank"),
        UniqueConstraint("tenant_id", "id", name="uq_native_calendars_tenant_id_id"),
        Index("ix_native_calendars_tenant_active", "tenant_id", "active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    @validates("name")
    def validate_name(self, _key: str, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("calendar_name_required")
        return value

    @validates("timezone")
    def validate_timezone(self, _key: str, value: str) -> str:
        return _validate_timezone(value)


class CalendarResource(Base):
    __tablename__ = "calendar_resources"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "calendar_id"],
            ["native_calendars.tenant_id", "native_calendars.id"],
            ondelete="CASCADE",
            name="fk_calendar_resources_tenant_calendar",
        ),
        CheckConstraint("length(trim(name)) > 0", name="ck_calendar_resources_name_not_blank"),
        UniqueConstraint("tenant_id", "calendar_id", "id", name="uq_calendar_resources_tenant_calendar_id"),
        Index("ix_calendar_resources_tenant_calendar_active", "tenant_id", "calendar_id", "active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    calendar_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    timezone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    @validates("name")
    def validate_name(self, _key: str, value: str) -> str:
        value = str(value or "").strip()
        if not value:
            raise ValueError("resource_name_required")
        return value

    @validates("timezone")
    def validate_timezone(self, _key: str, value: str | None) -> str | None:
        return None if value is None else _validate_timezone(value)


class AvailabilityRule(Base):
    __tablename__ = "availability_rules"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "calendar_id"], ["native_calendars.tenant_id", "native_calendars.id"],
            ondelete="CASCADE", name="fk_availability_rules_tenant_calendar",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "calendar_id", "resource_id"],
            ["calendar_resources.tenant_id", "calendar_resources.calendar_id", "calendar_resources.id"],
            ondelete="CASCADE", name="fk_availability_rules_tenant_calendar_resource",
        ),
        CheckConstraint("weekday >= 0 AND weekday <= 6", name="ck_availability_rules_weekday"),
        CheckConstraint("start_time < end_time", name="ck_availability_rules_time_order"),
        Index("ix_availability_rules_resource_weekday", "tenant_id", "resource_id", "weekday", "active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    calendar_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    weekday: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    start_time: Mapped[time] = mapped_column(Time, nullable=False)
    end_time: Mapped[time] = mapped_column(Time, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    @validates("weekday")
    def validate_weekday(self, _key: str, value: int) -> int:
        if not 0 <= value <= 6:
            raise ValueError("invalid_weekday")
        return value

    @validates("start_time", "end_time")
    def validate_time_order(self, key: str, value: time) -> time:
        other = getattr(self, "end_time" if key == "start_time" else "start_time", None)
        if other is not None and ((key == "start_time" and value >= other) or (key == "end_time" and other >= value)):
            raise ValueError("availability_start_must_precede_end")
        return value


class _InstantRangeMixin:
    @validates("start_at", "end_at")
    def validate_range(self, key: str, value: datetime) -> datetime:
        value = _validate_instant(value)
        other = getattr(self, "end_at" if key == "start_at" else "start_at", None)
        # SQLite drops tzinfo when materializing DateTime(timezone=True). The
        # persistence contract stores UTC instants, so normalize that test-only
        # representation before comparing; PostgreSQL values remain aware.
        if other is not None and (other.tzinfo is None or other.utcoffset() is None):
            other = other.replace(tzinfo=timezone.utc)
        if other is not None and ((key == "start_at" and value >= other) or (key == "end_at" and other >= value)):
            raise ValueError("start_must_precede_end")
        return value

    @validates("timezone")
    def validate_timezone(self, _key: str, value: str) -> str:
        return _validate_timezone(value)


class CalendarBlock(_InstantRangeMixin, Base):
    __tablename__ = "calendar_blocks"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "calendar_id"], ["native_calendars.tenant_id", "native_calendars.id"],
            ondelete="CASCADE", name="fk_calendar_blocks_tenant_calendar",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "calendar_id", "resource_id"],
            ["calendar_resources.tenant_id", "calendar_resources.calendar_id", "calendar_resources.id"],
            ondelete="CASCADE", name="fk_calendar_blocks_tenant_calendar_resource",
        ),
        CheckConstraint("start_at < end_at", name="ck_calendar_blocks_time_order"),
        Index("ix_calendar_blocks_resource_start", "tenant_id", "resource_id", "start_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    calendar_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)


class Appointment(_InstantRangeMixin, Base):
    __tablename__ = "appointments"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "calendar_id"], ["native_calendars.tenant_id", "native_calendars.id"],
            ondelete="CASCADE", name="fk_appointments_tenant_calendar",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "calendar_id", "resource_id"],
            ["calendar_resources.tenant_id", "calendar_resources.calendar_id", "calendar_resources.id"],
            ondelete="RESTRICT", name="fk_appointments_tenant_calendar_resource",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "contact_id"], ["contacts.tenant_id", "contacts.id"],
            ondelete="RESTRICT", name="fk_appointments_tenant_contact",
        ),
        CheckConstraint("start_at < end_at", name="ck_appointments_time_order"),
        CheckConstraint("status IN ('scheduled', 'cancelled', 'completed')", name="ck_appointments_status"),
        CheckConstraint("source IN ('assistant', 'manual', 'api')", name="ck_appointments_source"),
        Index("ix_appointments_resource_start", "tenant_id", "resource_id", "start_at"),
        Index("ix_appointments_contact_start", "tenant_id", "contact_id", "start_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False)
    calendar_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    resource_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    contact_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    service_reference: Mapped[str | None] = mapped_column(String(120), nullable=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="scheduled", server_default="scheduled")
    source: Mapped[str] = mapped_column(String(24), nullable=False)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    flow_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    @validates("status")
    def validate_status(self, _key: str, value: str) -> str:
        if value not in APPOINTMENT_STATUSES:
            raise ValueError("invalid_appointment_status")
        return value

    @validates("source")
    def validate_source(self, _key: str, value: str) -> str:
        if value not in APPOINTMENT_SOURCES:
            raise ValueError("invalid_appointment_source")
        return value
