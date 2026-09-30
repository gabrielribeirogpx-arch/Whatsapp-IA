"""CalendarProvider implementation backed by the tenant-owned Wazza calendar."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models.contact import Contact
from app.models.native_calendar import Appointment, AvailabilityRule, CalendarBlock, CalendarResource, NativeCalendar
from app.services.appointment_policy_service import DAYS, AppointmentPolicyError, appointments_for_availability
from app.services.audit_service import write_audit_log


class WazzaNativeCalendarProvider:
    """A fully tenant/contact scoped provider; binding IDs are server supplied."""

    def __init__(self, db: Any, tenant_id: UUID, contact_id: UUID | None, calendar_id: UUID, resource_id: UUID) -> None:
        self.db, self.tenant_id, self.contact_id = db, tenant_id, contact_id
        self.calendar_id, self.resource_id = calendar_id, resource_id

    @staticmethod
    def _failure(code: str) -> dict[str, Any]:
        return {"ok": False, "message": code}

    @staticmethod
    def _instant(value: Any, timezone_name: str) -> datetime:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name))
        return parsed.astimezone(timezone.utc)

    def _binding(self) -> tuple[NativeCalendar, CalendarResource] | tuple[None, str]:
        calendar = self.db.scalar(select(NativeCalendar).where(
            NativeCalendar.id == self.calendar_id, NativeCalendar.tenant_id == self.tenant_id
        ))
        if calendar is None:
            return None, "calendar_not_found"
        if not calendar.active:
            return None, "calendar_inactive"
        resource = self.db.scalar(select(CalendarResource).where(
            CalendarResource.id == self.resource_id,
            CalendarResource.calendar_id == self.calendar_id,
            CalendarResource.tenant_id == self.tenant_id,
        ))
        if resource is None:
            return None, "resource_not_found"
        if not resource.active:
            return None, "resource_inactive"
        return calendar, resource

    def _context(self) -> tuple[NativeCalendar, CalendarResource, str] | tuple[None, str]:
        binding = self._binding()
        if binding[0] is None:
            return binding
        calendar, resource = binding
        timezone_name = resource.timezone or calendar.timezone
        try:
            ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            return None, "invalid_timezone"
        return calendar, resource, timezone_name

    def _policy(self, timezone_name: str) -> dict[str, Any]:
        rules = self.db.scalars(select(AvailabilityRule).where(
            AvailabilityRule.tenant_id == self.tenant_id,
            AvailabilityRule.calendar_id == self.calendar_id,
            AvailabilityRule.resource_id == self.resource_id,
            AvailabilityRule.active.is_(True),
        )).all()
        hours = {day: [] for day in DAYS}
        for rule in sorted(rules, key=lambda row: (row.weekday, row.start_time)):
            hours[DAYS[rule.weekday]].append({
                "start": rule.start_time.strftime("%H:%M"), "end": rule.end_time.strftime("%H:%M")
            })
        return {"timezone": timezone_name, "default_duration_minutes": 60,
                "slot_interval_minutes": 60, "input_mode": "exact_or_period", "business_hours": hours}

    def _busy(self, start: datetime, end: datetime, *, exclude_id: UUID | None = None) -> list[dict[str, str]]:
        blocks = self.db.scalars(select(CalendarBlock).where(
            CalendarBlock.tenant_id == self.tenant_id, CalendarBlock.calendar_id == self.calendar_id,
            CalendarBlock.resource_id == self.resource_id, CalendarBlock.start_at < end, CalendarBlock.end_at > start,
        )).all()
        query = select(Appointment).where(
            Appointment.tenant_id == self.tenant_id, Appointment.calendar_id == self.calendar_id,
            Appointment.resource_id == self.resource_id, Appointment.status != "cancelled",
            Appointment.start_at < end, Appointment.end_at > start,
        )
        if exclude_id is not None:
            query = query.where(Appointment.id != exclude_id)
        appointments = self.db.scalars(query).all()
        return [{"start": row.start_at.isoformat(), "end": row.end_at.isoformat()} for row in [*blocks, *appointments]]

    def _window(self, kwargs: dict[str, Any], timezone_name: str) -> tuple[datetime, datetime] | None:
        try:
            start = self._instant(kwargs.get("start") or kwargs.get("timeMin") or kwargs.get("time_min"), timezone_name)
            end = self._instant(kwargs.get("end") or kwargs.get("timeMax") or kwargs.get("time_max"), timezone_name)
            return (start, end) if end > start else None
        except (ValueError, TypeError):
            return None

    def check_availability(self, **kwargs: Any) -> dict[str, Any]:
        context = self._context()
        if context[0] is None:
            return self._failure(context[1])
        _, _, timezone_name = context
        window = self._window(kwargs, timezone_name)
        if window is None:
            return self._failure("invalid_period")
        start, end = window
        busy = self._busy(start, end)
        try:
            appointments = appointments_for_availability(
                start=start.isoformat(), end=end.isoformat(), timezone=timezone_name, busy=busy,
                policy=self._policy(timezone_name), mode=str(kwargs.get("mode") or "period"),
                duration_minutes=kwargs.get("_effective_duration_minutes"),
            )
        except AppointmentPolicyError as exc:
            return self._failure(exc.code)
        return {"ok": True, "busy": busy, "appointments": appointments}

    def _trusted_contact(self) -> bool:
        return self.contact_id is not None and self.db.scalar(select(Contact.id).where(
            Contact.id == self.contact_id, Contact.tenant_id == self.tenant_id
        )) is not None

    def _slot_error(self, start: datetime, end: datetime, timezone_name: str, exclude_id: UUID | None = None) -> str | None:
        duration = int((end - start).total_seconds() // 60)
        try:
            available = appointments_for_availability(
                start=start.isoformat(), end=end.isoformat(), timezone=timezone_name,
                busy=self._busy(start, end, exclude_id=exclude_id), policy=self._policy(timezone_name),
                mode="exact", duration_minutes=duration,
            )
        except AppointmentPolicyError:
            return "invalid_period"
        if available:
            return None
        return "slot_conflict" if self._busy(start, end, exclude_id=exclude_id) else "outside_availability"

    def create_event(self, *, asa_private_metadata: dict[str, str] | None = None, **kwargs: Any) -> dict[str, Any]:
        context = self._context()
        if context[0] is None:
            return self._failure(context[1])
        if not self._trusted_contact():
            return self._failure("contact_not_found")
        _, _, timezone_name = context
        window = self._window(kwargs, timezone_name)
        if window is None:
            return self._failure("invalid_period")
        start, end = window
        error = self._slot_error(start, end, timezone_name)
        if error:
            return self._failure(error)
        row = Appointment(
            tenant_id=self.tenant_id, calendar_id=self.calendar_id, resource_id=self.resource_id,
            contact_id=self.contact_id, start_at=start, end_at=end, timezone=timezone_name,
            status="scheduled", source="assistant", service_reference=kwargs.get("service_reference"),
            conversation_id=kwargs.get("_conversation_id"), flow_id=kwargs.get("_flow_id"),
        )
        try:
            with self.db.begin_nested():
                self.db.add(row)
                self.db.flush()
        except IntegrityError:
            return self._failure("slot_conflict")
        write_audit_log(self.db, action="appointment.created", tenant_id=self.tenant_id,
                        entity_type="appointment", entity_id=row.id,
                        metadata={"calendar_id": self.calendar_id, "resource_id": self.resource_id})
        return self._dto(row)

    @staticmethod
    def _dto(row: Appointment) -> dict[str, Any]:
        return {"ok": True, "event_id": str(row.id), "id": str(row.id), "start": row.start_at.isoformat(),
                "end": row.end_at.isoformat(), "timezone": row.timezone, "status": row.status}

    def find_managed_appointments(self, *, start: str, end: str, timezone: str | None,
                                  patient_ref: str, metadata_schema: str) -> dict[str, Any]:
        return self._list_owned(start=start, end=end)

    def _list_owned(self, **kwargs: Any) -> dict[str, Any]:
        context = self._context()
        if context[0] is None:
            return self._failure(context[1])
        if not self._trusted_contact():
            return self._failure("contact_not_found")
        _, _, timezone_name = context
        window = self._window(kwargs, timezone_name)
        if window is None:
            return self._failure("invalid_period")
        start, end = window
        rows = self.db.scalars(select(Appointment).where(
            Appointment.tenant_id == self.tenant_id, Appointment.calendar_id == self.calendar_id,
            Appointment.resource_id == self.resource_id, Appointment.contact_id == self.contact_id,
            Appointment.start_at < end, Appointment.end_at > start,
        ).order_by(Appointment.start_at).limit(250)).all()
        return {"ok": True, "events": [self._dto(row) | {"ok": True} for row in rows],
                "appointments": [self._dto(row) | {"ok": True} for row in rows]}

    def list_events(self, **kwargs: Any) -> dict[str, Any]:
        return self._list_owned(**kwargs)

    def _owned(self, event_id: str) -> Appointment | None:
        try:
            appointment_id = UUID(str(event_id))
        except ValueError:
            return None
        return self.db.scalar(select(Appointment).where(
            Appointment.id == appointment_id, Appointment.tenant_id == self.tenant_id,
            Appointment.calendar_id == self.calendar_id, Appointment.resource_id == self.resource_id,
            Appointment.contact_id == self.contact_id,
        ))

    def update_event(self, event_id: str, **kwargs: Any) -> dict[str, Any]:
        context = self._context()
        if context[0] is None:
            return self._failure(context[1])
        row = self._owned(event_id)
        if row is None or row.status != "scheduled":
            return self._failure("appointment_not_found")
        _, _, timezone_name = context
        window = self._window(kwargs, timezone_name)
        if window is None:
            return self._failure("invalid_period")
        start, end = window
        error = self._slot_error(start, end, timezone_name, row.id)
        if error:
            return self._failure(error)
        try:
            with self.db.begin_nested():
                old_start = row.start_at.replace(tzinfo=timezone.utc) if row.start_at.tzinfo is None else row.start_at
                if start >= old_start:
                    row.end_at, row.start_at = end, start
                else:
                    row.start_at, row.end_at = start, end
                row.timezone = timezone_name
                self.db.flush()
        except IntegrityError:
            return self._failure("slot_conflict")
        write_audit_log(self.db, action="appointment.rescheduled", tenant_id=self.tenant_id,
                        entity_type="appointment", entity_id=row.id,
                        metadata={"calendar_id": self.calendar_id, "resource_id": self.resource_id})
        return self._dto(row)

    def delete_event(self, event_id: str) -> dict[str, Any]:
        if self._context()[0] is None:
            context = self._context()
            return self._failure(context[1])
        row = self._owned(event_id)
        if row is None:
            return self._failure("appointment_not_found")
        row.status = "cancelled"
        self.db.flush()
        write_audit_log(self.db, action="appointment.cancelled", tenant_id=self.tenant_id,
                        entity_type="appointment", entity_id=row.id,
                        metadata={"calendar_id": self.calendar_id, "resource_id": self.resource_id})
        return {"ok": True, "deleted": True, "event_id": str(row.id)}
