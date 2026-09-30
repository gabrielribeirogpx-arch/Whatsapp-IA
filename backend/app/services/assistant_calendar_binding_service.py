"""Transactional calendar binding and native-calendar provisioning for assistants."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.integration_connection import IntegrationConnection
from app.models.marketplace_installation import AssistantCalendarBinding, MarketplaceInstallation, MarketplaceInstallationResource
from app.models.native_calendar import AvailabilityRule, CalendarResource, NativeCalendar
from app.schemas.assistant_configuration import AssistantConfigurationV1
from app.services.appointment_policy_service import DAYS, policy_for_tenant
from app.services.audit_service import write_audit_log


def _tracked_uuid(installation: MarketplaceInstallation, kind: str) -> UUID | None:
    item = next((row for row in installation.resources if row.resource_type == kind), None)
    try:
        return UUID(item.resource_id) if item else None
    except ValueError:
        return None


def _native(db: Session, installation: MarketplaceInstallation, configuration: AssistantConfigurationV1,
            actor_id: UUID, request) -> tuple[NativeCalendar, CalendarResource]:
    calendar_id, resource_id = _tracked_uuid(installation, "native_calendar"), _tracked_uuid(installation, "calendar_resource")
    calendar = db.scalar(select(NativeCalendar).where(NativeCalendar.id == calendar_id, NativeCalendar.tenant_id == installation.tenant_id)) if calendar_id else None
    resource = db.scalar(select(CalendarResource).where(
        CalendarResource.id == resource_id, CalendarResource.tenant_id == installation.tenant_id,
        CalendarResource.calendar_id == calendar.id,
    )) if resource_id and calendar else None
    calendar_config = configuration.calendar
    policy = policy_for_tenant(db, installation.tenant_id)
    timezone_name = calendar_config.timezone if calendar_config and calendar_config.timezone else policy["timezone"]
    name = configuration.clinic_name
    created = False
    if calendar is None:
        calendar = NativeCalendar(tenant_id=installation.tenant_id, name=f"Agenda · {name}", timezone=timezone_name)
        db.add(calendar)
        db.flush()
        created = True
        installation.resources.append(MarketplaceInstallationResource(
            installation_id=installation.id, resource_type="native_calendar", resource_id=str(calendar.id),
            resource_name=calendar.name, creation_status="created", metadata_json={"ownership": str(installation.id)},
        ))
    else:
        calendar.name, calendar.timezone, calendar.active = f"Agenda · {name}", timezone_name, True
    if resource is None:
        resource_name = calendar_config.resource_name if calendar_config and calendar_config.resource_name else "Profissional principal"
        resource = CalendarResource(tenant_id=installation.tenant_id, calendar_id=calendar.id,
                                    name=resource_name, timezone=timezone_name)
        db.add(resource)
        db.flush()
        created = True
        installation.resources.append(MarketplaceInstallationResource(
            installation_id=installation.id, resource_type="calendar_resource", resource_id=str(resource.id),
            resource_name=resource.name, creation_status="created", metadata_json={"ownership": str(installation.id)},
        ))
    else:
        resource.timezone, resource.active = timezone_name, True
    hours = calendar_config.business_hours if calendar_config and calendar_config.business_hours is not None else policy["business_hours"]
    db.execute(delete(AvailabilityRule).where(
        AvailabilityRule.tenant_id == installation.tenant_id,
        AvailabilityRule.calendar_id == calendar.id, AvailabilityRule.resource_id == resource.id,
    ))
    from datetime import time
    for weekday, day in enumerate(DAYS):
        for period in hours.get(day, []):
            start_h, start_m = map(int, period["start"].split(":"))
            end_h, end_m = map(int, period["end"].split(":"))
            db.add(AvailabilityRule(tenant_id=installation.tenant_id, calendar_id=calendar.id,
                                    resource_id=resource.id, weekday=weekday,
                                    start_time=time(start_h, start_m), end_time=time(end_h, end_m)))
    if created:
        write_audit_log(db, action="assistant.native_calendar_provisioned", tenant_id=installation.tenant_id,
                        user_id=actor_id, entity_type="marketplace_installation", entity_id=installation.id,
                        metadata={"calendar_id": calendar.id, "resource_id": resource.id}, request=request)
    return calendar, resource


def bind_assistant_calendar(db: Session, *, installation: MarketplaceInstallation,
                            configuration: AssistantConfigurationV1, actor_id: UUID, request) -> AssistantCalendarBinding:
    provider = configuration.effective_calendar_provider
    binding = db.scalar(select(AssistantCalendarBinding).where(
        AssistantCalendarBinding.installation_id == installation.id,
        AssistantCalendarBinding.tenant_id == installation.tenant_id,
    ).with_for_update())
    before = binding.provider if binding else None
    connection_id = calendar_id = resource_id = None
    if provider == "google_calendar":
        connection_id = configuration.google_calendar_connection_id
        connection = db.scalar(select(IntegrationConnection).where(
            IntegrationConnection.id == connection_id, IntegrationConnection.tenant_id == installation.tenant_id,
            IntegrationConnection.provider == "google_calendar", IntegrationConnection.status == "active",
        ))
        if connection is None:
            raise HTTPException(422, "invalid_google_calendar_connection")
    else:
        calendar, resource = _native(db, installation, configuration, actor_id, request)
        calendar_id, resource_id = calendar.id, resource.id
    if binding is None:
        binding = AssistantCalendarBinding(tenant_id=installation.tenant_id, installation_id=installation.id,
                                           provider=provider)
        db.add(binding)
    binding.provider = provider
    binding.integration_connection_id = connection_id
    binding.native_calendar_id = calendar_id
    binding.native_resource_id = resource_id
    binding.updated_at = datetime.utcnow()
    db.flush()
    if before != provider:
        write_audit_log(db, action="assistant.calendar_provider_changed", tenant_id=installation.tenant_id,
                        user_id=actor_id, entity_type="assistant_calendar_binding", entity_id=binding.id,
                        metadata={"installation_id": installation.id, "before": before, "after": provider}, request=request)
    return binding


def effective_binding(db: Session, installation: MarketplaceInstallation,
                      configuration: AssistantConfigurationV1) -> AssistantCalendarBinding | None:
    binding = db.scalar(select(AssistantCalendarBinding).where(
        AssistantCalendarBinding.installation_id == installation.id,
        AssistantCalendarBinding.tenant_id == installation.tenant_id,
    ))
    if binding is not None:
        return binding
    # Legacy rows remain Google without requiring a data migration.
    return None


def binding_is_valid(db: Session, binding: AssistantCalendarBinding) -> bool:
    if binding.provider == "google_calendar":
        return db.scalar(select(IntegrationConnection.id).where(
            IntegrationConnection.id == binding.integration_connection_id,
            IntegrationConnection.tenant_id == binding.tenant_id,
            IntegrationConnection.provider == "google_calendar",
            IntegrationConnection.status == "active",
        )) is not None
    if binding.provider == "wazza_native":
        calendar = db.scalar(select(NativeCalendar).where(
            NativeCalendar.id == binding.native_calendar_id,
            NativeCalendar.tenant_id == binding.tenant_id,
            NativeCalendar.active.is_(True),
        ))
        resource = db.scalar(select(CalendarResource).where(
            CalendarResource.id == binding.native_resource_id,
            CalendarResource.tenant_id == binding.tenant_id,
            CalendarResource.calendar_id == binding.native_calendar_id,
            CalendarResource.active.is_(True),
        ))
        return calendar is not None and resource is not None
    return False
