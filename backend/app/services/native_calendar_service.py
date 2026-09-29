"""Tenant-bound persistence operations for the native calendar domain.

This module deliberately does not implement ``CalendarProvider``. PostgreSQL's
exclusion constraint remains the authoritative concurrent double-booking guard;
the overlap query below provides an early, portable domain error (including in
SQLite unit tests), but is not treated as a concurrency lock.
"""

from __future__ import annotations

from typing import TypeVar
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.contact import Contact
from app.models.native_calendar import (
    Appointment,
    AvailabilityRule,
    CalendarBlock,
    CalendarResource,
    NativeCalendar,
)


class NativeCalendarError(ValueError):
    pass


T = TypeVar("T")


def _tenant_row(db: Session, model: type[T], tenant_id: UUID, row_id: UUID, code: str) -> T:
    row = db.scalar(select(model).where(model.id == row_id, model.tenant_id == tenant_id))
    if row is None:
        raise NativeCalendarError(code)
    return row


class NativeCalendarService:
    def __init__(self, db: Session, *, tenant_id: UUID):
        self.db = db
        self.tenant_id = tenant_id

    def create_calendar(self, **values) -> NativeCalendar:
        row = NativeCalendar(tenant_id=self.tenant_id, **values)
        self.db.add(row)
        self.db.flush()
        return row

    def create_resource(self, *, calendar_id: UUID, **values) -> CalendarResource:
        _tenant_row(self.db, NativeCalendar, self.tenant_id, calendar_id, "calendar_not_found")
        row = CalendarResource(tenant_id=self.tenant_id, calendar_id=calendar_id, **values)
        self.db.add(row)
        self.db.flush()
        return row

    def _resource(self, calendar_id: UUID, resource_id: UUID) -> CalendarResource:
        row = self.db.scalar(
            select(CalendarResource).where(
                CalendarResource.tenant_id == self.tenant_id,
                CalendarResource.calendar_id == calendar_id,
                CalendarResource.id == resource_id,
            )
        )
        if row is None:
            raise NativeCalendarError("resource_not_found")
        return row

    def create_availability_rule(self, *, calendar_id: UUID, resource_id: UUID, **values) -> AvailabilityRule:
        self._resource(calendar_id, resource_id)
        row = AvailabilityRule(
            tenant_id=self.tenant_id, calendar_id=calendar_id, resource_id=resource_id, **values
        )
        self.db.add(row)
        self.db.flush()
        return row

    def create_block(self, *, calendar_id: UUID, resource_id: UUID, **values) -> CalendarBlock:
        self._resource(calendar_id, resource_id)
        row = CalendarBlock(
            tenant_id=self.tenant_id, calendar_id=calendar_id, resource_id=resource_id, **values
        )
        self.db.add(row)
        self.db.flush()
        return row

    def create_appointment(
        self, *, calendar_id: UUID, resource_id: UUID, contact_id: UUID, **values
    ) -> Appointment:
        self._resource(calendar_id, resource_id)
        _tenant_row(self.db, Contact, self.tenant_id, contact_id, "contact_not_found")

        row = Appointment(
            tenant_id=self.tenant_id,
            calendar_id=calendar_id,
            resource_id=resource_id,
            contact_id=contact_id,
            **values,
        )
        start_at = row.start_at
        end_at = row.end_at
        status = row.status or "scheduled"
        if status != "cancelled" and start_at is not None and end_at is not None:
            conflict = self.db.scalar(
                select(Appointment.id).where(
                    Appointment.tenant_id == self.tenant_id,
                    Appointment.resource_id == resource_id,
                    Appointment.status != "cancelled",
                    Appointment.start_at < end_at,
                    Appointment.end_at > start_at,
                ).limit(1)
            )
            if conflict is not None:
                raise NativeCalendarError("appointment_conflict")

        self.db.add(row)
        self.db.flush()
        return row
