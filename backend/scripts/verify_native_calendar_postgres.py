"""Conservative, destructive-by-ID PostgreSQL gate for the native calendar.

Run manually from ``backend`` only after selecting the intended Railway
environment.  The script creates two wholly artificial tenants and deletes only
the UUIDs it generated during this invocation.  It never prints the database
URL or connection errors (which can contain credentials).
"""

from __future__ import annotations

import io
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from datetime import datetime, time as wall_time, timezone
from queue import Queue
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError

from app.db.session import SessionLocal, engine
from app.models.audit_log import AuditLog
from app.models.contact import Contact
from app.models.native_calendar import (
    Appointment,
    AvailabilityRule,
    CalendarResource,
    NativeCalendar,
)
from app.models.tenant import Tenant
from app.services.calendar_provider_resolver import CalendarProviderResolver
from app.tools.context import ToolContext


EXPECTED_REVISION = "20260930_calendar_binding"
CONSTRAINT_NAME = "ex_appointments_resource_time"
LOCK_TIMEOUT = "8s"
STATEMENT_TIMEOUT = "12s"
WAIT_OBSERVATION_TIMEOUT_SECONDS = 6.0
UTC = timezone.utc


class GateFailure(RuntimeError):
    """A safe failure whose text contains no database details."""


@dataclass
class CreatedIds:
    tenants: set[UUID] = field(default_factory=set)
    contacts: set[UUID] = field(default_factory=set)
    calendars: set[UUID] = field(default_factory=set)
    resources: set[UUID] = field(default_factory=set)
    availability_rules: set[UUID] = field(default_factory=set)
    appointments: set[UUID] = field(default_factory=set)
    audit_logs: set[UUID] = field(default_factory=set)

    def technical_ids(self) -> list[str]:
        groups = (
            ("tenant", self.tenants),
            ("contact", self.contacts),
            ("calendar", self.calendars),
            ("resource", self.resources),
            ("availability_rule", self.availability_rules),
            ("appointment", self.appointments),
            ("audit_log", self.audit_logs),
        )
        return [f"{kind}:{value}" for kind, values in groups for value in sorted(values, key=str)]


def set_timeouts(db: Any) -> None:
    db.execute(text("SELECT set_config('lock_timeout', :value, true)"), {"value": LOCK_TIMEOUT})
    db.execute(text("SELECT set_config('statement_timeout', :value, true)"), {"value": STATEMENT_TIMEOUT})


def preflight() -> str:
    if engine.dialect.name != "postgresql":
        raise GateFailure("PostgreSQL is required (no test data was created).")
    try:
        with engine.connect() as connection:
            revisions = connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
            if revisions != [EXPECTED_REVISION]:
                raise GateFailure("Unexpected Alembic revision (no test data was created).")
            definition = connection.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conname = :name AND conrelid = 'appointments'::regclass"
                ),
                {"name": CONSTRAINT_NAME},
            ).scalar_one_or_none()
    except GateFailure:
        raise
    except Exception as exc:
        raise GateFailure("Database preflight failed safely (no test data was created).") from exc
    normalized = " ".join(str(definition or "").lower().split())
    required = ("exclude using gist", "tenant_id with =", "resource_id with =", "tstzrange", "'[)'", "with &&", "cancelled")
    if not definition or any(fragment not in normalized for fragment in required):
        raise GateFailure("Expected appointment exclusion constraint was not found (no test data was created).")
    return definition


def appointment(
    ids: CreatedIds,
    *,
    tenant_id: UUID,
    calendar_id: UUID,
    resource_id: UUID,
    contact_id: UUID,
    start: datetime,
    end: datetime,
    status: str = "scheduled",
) -> Appointment:
    appointment_id = uuid4()
    ids.appointments.add(appointment_id)
    return Appointment(
        id=appointment_id,
        tenant_id=tenant_id,
        calendar_id=calendar_id,
        resource_id=resource_id,
        contact_id=contact_id,
        start_at=start,
        end_at=end,
        timezone="UTC",
        status=status,
        source="api",
        service_reference="wazza-postgresql-gate",
    )


def create_fixture(db: Any, ids: CreatedIds, prefix: str, suffix: str) -> tuple[Tenant, Contact, NativeCalendar, CalendarResource]:
    tenant = Tenant(id=uuid4(), name=f"{prefix}_{suffix}", slug=f"{prefix.lower().replace('_', '-')}-{suffix}")
    contact = Contact(id=uuid4(), tenant_id=tenant.id, phone=f"gate-{uuid4().hex}", name=f"{prefix}_{suffix}_contact")
    calendar = NativeCalendar(id=uuid4(), tenant_id=tenant.id, name=f"{prefix}_{suffix}_calendar", timezone="UTC")
    resource = CalendarResource(
        id=uuid4(), tenant_id=tenant.id, calendar_id=calendar.id, name=f"{prefix}_{suffix}_resource", timezone="UTC"
    )
    ids.tenants.add(tenant.id)
    ids.contacts.add(contact.id)
    ids.calendars.add(calendar.id)
    ids.resources.add(resource.id)
    db.add(tenant)
    db.flush()
    db.add_all((contact, calendar))
    db.flush()
    db.add(resource)
    db.flush()
    return tenant, contact, calendar, resource


def resolver_provider(db: Any, tenant: Tenant, contact: Contact, calendar: NativeCalendar, resource: CalendarResource) -> Any:
    return CalendarProviderResolver(db).resolve(
        ToolContext(
            tenant_id=tenant.id,
            contact_id=contact.id,
            calendar_provider="wazza_native",
            native_calendar_id=calendar.id,
            native_resource_id=resource.id,
        )
    )


def competing_insert(row: Appointment, pid_queue: Queue[int]) -> str:
    """Insert on a genuinely independent session and report only safe outcomes."""
    with SessionLocal() as db:
        try:
            set_timeouts(db)
            pid_queue.put(db.scalar(text("SELECT pg_backend_pid()")))
            db.add(row)
            db.flush()  # Expected to wait on transaction A's speculative GiST conflict.
            db.commit()
            return "commit"
        except IntegrityError as exc:
            db.rollback()
            original = exc.orig
            sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
            constraint = getattr(getattr(original, "diag", None), "constraint_name", None)
            return "conflict" if sqlstate == "23P01" and constraint == CONSTRAINT_NAME else "unexpected_integrity"
        except Exception:
            db.rollback()
            return "unexpected_error"


def concurrency_gate(
    ids: CreatedIds, tenant: Tenant, contact: Contact, calendar: NativeCalendar, resource: CalendarResource
) -> tuple[int, int, int]:
    start = datetime(2035, 1, 8, 9, 0, tzinfo=UTC)
    end = datetime(2035, 1, 8, 9, 30, tzinfo=UTC)
    row_a = appointment(ids, tenant_id=tenant.id, calendar_id=calendar.id, resource_id=resource.id,
                        contact_id=contact.id, start=start, end=end)
    row_b = appointment(ids, tenant_id=tenant.id, calendar_id=calendar.id, resource_id=resource.id,
                        contact_id=contact.id, start=start, end=end)
    pid_queue: Queue[int] = Queue(maxsize=1)
    result_a = "unexpected_error"
    result_b = "unexpected_error"
    with SessionLocal() as tx_a:
        set_timeouts(tx_a)
        tx_a.add(row_a)
        tx_a.flush()
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix="wazza-pg-gate") as executor:
            future = executor.submit(competing_insert, row_b, pid_queue)
            try:
                pid_b = pid_queue.get(timeout=2.0)
            except Exception as exc:
                tx_a.rollback()
                raise GateFailure("Independent transaction did not start in time.") from exc
            deadline = time.monotonic() + WAIT_OBSERVATION_TIMEOUT_SECONDS
            observed_lock = False
            while time.monotonic() < deadline:
                with engine.connect() as observer:
                    wait_type = observer.execute(
                        text("SELECT wait_event_type FROM pg_stat_activity WHERE pid = :pid"), {"pid": pid_b}
                    ).scalar_one_or_none()
                if wait_type == "Lock":
                    observed_lock = True
                    break
                time.sleep(0.05)
            if not observed_lock:
                tx_a.rollback()
                result_b = future.result(timeout=15.0)
                raise GateFailure(f"PostgreSQL lock wait was not observed (TX B: {result_b}).")
            tx_a.commit()
            result_a = "commit"
            result_b = future.result(timeout=15.0)

    winners = int(result_a == "commit") + int(result_b == "commit")
    conflicts = int(result_a == "conflict") + int(result_b == "conflict")
    with SessionLocal() as db:
        active = db.scalar(
            select(func.count()).select_from(Appointment).where(
                Appointment.tenant_id == tenant.id,
                Appointment.resource_id == resource.id,
                Appointment.status != "cancelled",
                Appointment.start_at < end,
                Appointment.end_at > start,
            )
        )
    if (winners, conflicts, active) != (1, 1, 1):
        raise GateFailure(f"Concurrency invariant failed (TX A: {result_a}; TX B: {result_b}).")
    return winners, conflicts, int(active)


def cleanup(ids: CreatedIds) -> bool:
    """Delete only exact UUIDs generated or discovered for this isolated run."""
    try:
        with SessionLocal() as db:
            # Provider audit IDs are discovered inside artificial tenant IDs, then
            # converted to an exact-ID delete like every other object below.
            if ids.tenants:
                ids.audit_logs.update(
                    db.scalars(select(AuditLog.id).where(AuditLog.tenant_id.in_(ids.tenants))).all()
                )
            ordered = (
                (AuditLog, ids.audit_logs),
                (Appointment, ids.appointments),
                (AvailabilityRule, ids.availability_rules),
                (CalendarResource, ids.resources),
                (NativeCalendar, ids.calendars),
                (Contact, ids.contacts),
                (Tenant, ids.tenants),
            )
            for model, values in ordered:
                if values:
                    db.execute(delete(model).where(model.id.in_(values)))
            db.commit()
        with SessionLocal() as verify:
            checks = (
                (Appointment, ids.appointments),
                (CalendarResource, ids.resources),
                (NativeCalendar, ids.calendars),
                (Contact, ids.contacts),
                (Tenant, ids.tenants),
                (AvailabilityRule, ids.availability_rules),
                (AuditLog, ids.audit_logs),
            )
            return all(
                not values or verify.scalar(select(func.count()).select_from(model).where(model.id.in_(values))) == 0
                for model, values in checks
            )
    except Exception:
        return False


def run() -> int:
    print("WAZZA NATIVE CALENDAR — POSTGRESQL GATE\n")
    ids = CreatedIds()
    gate_ok = False
    cleanup_ok = True
    try:
        preflight()
        print("Database:\nPostgreSQL detected: PASS")
        print(f"Alembic revision: {EXPECTED_REVISION}\n")
        print(f"Constraint:\n{CONSTRAINT_NAME}: PASS\n")

        run_id = uuid4()
        prefix = f"__wazza_pg_gate_{run_id}"
        with SessionLocal() as setup:
            setup.expire_on_commit = False
            set_timeouts(setup)
            tenant_a, contact_a, calendar_a, resource_a = create_fixture(setup, ids, prefix, "a")
            tenant_b, contact_b, calendar_b, resource_b = create_fixture(setup, ids, prefix, "b")
            resource_a2 = CalendarResource(
                id=uuid4(), tenant_id=tenant_a.id, calendar_id=calendar_a.id,
                name=f"{prefix}_a_resource_2", timezone="UTC",
            )
            ids.resources.add(resource_a2.id)
            rule = AvailabilityRule(
                id=uuid4(), tenant_id=tenant_a.id, calendar_id=calendar_a.id, resource_id=resource_a.id,
                weekday=0, start_time=wall_time(0, 0), end_time=wall_time(23, 59), active=True,
            )
            ids.availability_rules.add(rule.id)
            setup.add_all((resource_a2, rule))
            setup.commit()

        winners, conflicts, active = concurrency_gate(ids, tenant_a, contact_a, calendar_a, resource_a)
        print("Concurrency:\nindependent transactions: PASS")
        print("TX A: PASS / COMMIT\nTX B: CONFLICT")
        print(f"winner count: {winners}\nconflict count: {conflicts}\nactive overlapping appointments: {active}\n")

        with SessionLocal() as db:
            set_timeouts(db)
            provider = resolver_provider(db, tenant_a, contact_a, calendar_a, resource_a)
            provider_start = datetime(2035, 1, 8, 16, 0, tzinfo=UTC)
            provider_end = datetime(2035, 1, 8, 16, 30, tzinfo=UTC)
            db.add(appointment(ids, tenant_id=tenant_a.id, calendar_id=calendar_a.id, resource_id=resource_a.id,
                               contact_id=contact_a.id, start=provider_start, end=provider_end))
            db.flush()
            provider_result = provider.create_event(start=provider_start.isoformat(), end=provider_end.isoformat())
            if provider_result != {"ok": False, "message": "slot_conflict"}:
                raise GateFailure("Provider did not normalize a conflict as slot_conflict.")
            print("Provider normalization:\nslot_conflict: PASS\n")

            adjacent = ((10, 0, 10, 30), (10, 30, 11, 0))
            for start_h, start_m, end_h, end_m in adjacent:
                db.add(appointment(
                    ids, tenant_id=tenant_a.id, calendar_id=calendar_a.id, resource_id=resource_a.id,
                    contact_id=contact_a.id, start=datetime(2035, 1, 8, start_h, start_m, tzinfo=UTC),
                    end=datetime(2035, 1, 8, end_h, end_m, tzinfo=UTC),
                ))
                db.flush()
            print("Adjacent intervals:\n10:00-10:30: PASS\n10:30-11:00: PASS\n")

            cancel_row = appointment(
                ids, tenant_id=tenant_a.id, calendar_id=calendar_a.id, resource_id=resource_a.id,
                contact_id=contact_a.id, start=datetime(2035, 1, 8, 12, 0, tzinfo=UTC),
                end=datetime(2035, 1, 8, 12, 30, tzinfo=UTC),
            )
            db.add(cancel_row)
            db.flush()
            with redirect_stdout(io.StringIO()):
                cancel_result = provider.delete_event(str(cancel_row.id))
            if not cancel_result.get("ok") or cancel_row.status != "cancelled":
                raise GateFailure("Logical cancellation failed.")
            replacement = appointment(
                ids, tenant_id=tenant_a.id, calendar_id=calendar_a.id, resource_id=resource_a.id,
                contact_id=contact_a.id, start=datetime(2035, 1, 8, 12, 0, tzinfo=UTC),
                end=datetime(2035, 1, 8, 12, 30, tzinfo=UTC),
            )
            db.add(replacement)
            db.flush()
            if cancel_row.status != "cancelled" or replacement.status != "scheduled":
                raise GateFailure("Cancelled slot reuse invariant failed.")
            print("Cancellation:\nlogical cancellation: PASS\nslot reuse: PASS\n")

            for resource in (resource_a, resource_a2):
                db.add(appointment(
                    ids, tenant_id=tenant_a.id, calendar_id=calendar_a.id, resource_id=resource.id,
                    contact_id=contact_a.id, start=datetime(2035, 1, 8, 14, 0, tzinfo=UTC),
                    end=datetime(2035, 1, 8, 14, 30, tzinfo=UTC),
                ))
                db.flush()
            print("Resource isolation:\nPASS\n")

            for tenant, contact, calendar, resource in (
                (tenant_a, contact_a, calendar_a, resource_a),
                (tenant_b, contact_b, calendar_b, resource_b),
            ):
                db.add(appointment(
                    ids, tenant_id=tenant.id, calendar_id=calendar.id, resource_id=resource.id,
                    contact_id=contact.id, start=datetime(2035, 1, 8, 15, 0, tzinfo=UTC),
                    end=datetime(2035, 1, 8, 15, 30, tzinfo=UTC),
                ))
                db.flush()
            cross_tenant = resolver_provider(db, tenant_b, contact_b, calendar_a, resource_a).create_event(
                start=datetime(2035, 1, 8, 17, 0, tzinfo=UTC).isoformat(),
                end=datetime(2035, 1, 8, 17, 30, tzinfo=UTC).isoformat(),
            )
            if cross_tenant != {"ok": False, "message": "calendar_not_found"}:
                raise GateFailure("Cross-tenant provider reference was not rejected.")
            print("Tenant isolation:\nPASS (independent slots and cross-tenant rejection)\n")
            db.commit()
        gate_ok = True
    except GateFailure as exc:
        print(f"GATE: FAIL — {exc}")
    except Exception:
        # Deliberately omit exception details: DBAPI errors may embed SQL or DSNs.
        print("GATE: FAIL — unexpected safe failure; no SQL, URL, or credentials are displayed.")
    finally:
        if ids.tenants or ids.contacts or ids.calendars or ids.resources or ids.appointments:
            cleanup_ok = cleanup(ids)
        print(f"\nCleanup:\n{'PASS' if cleanup_ok else 'FAIL'}")
        if not cleanup_ok:
            print("Manual cleanup technical IDs:")
            for technical_id in ids.technical_ids():
                print(technical_id)
    passed = gate_ok and cleanup_ok
    print(f"\nFINAL RESULT:\n{'PASS' if passed else 'FAIL'}")
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(run())
