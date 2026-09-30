from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _plain_text(value: str, field: str) -> str:
    value = value.strip()
    if not value:
        raise ValueError(f"{field}_empty")
    if "<" in value or ">" in value or re.search(r"javascript\s*:", value, re.I):
        raise ValueError(f"{field}_markup_not_allowed")
    return value


class AssistantServiceV1(StrictModel):
    id: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=120)
    duration_minutes: int = Field(ge=5, le=480, strict=True)

    @field_validator("id", mode="before")
    @classmethod
    def normalize_id(cls, value: object) -> str:
        if not isinstance(value, str):
            raise ValueError("service_id_invalid")
        normalized = unicodedata.normalize("NFKD", value.strip().lower())
        normalized = "".join(c for c in normalized if not unicodedata.combining(c))
        normalized = re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")
        if not normalized or len(normalized) > 64:
            raise ValueError("service_id_invalid")
        return normalized

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: str) -> str:
        return _plain_text(value, "service_label")


class AssistantHandoffV1(StrictModel):
    enabled: bool = Field(strict=True)
    reason: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str | None) -> str | None:
        return _plain_text(value, "handoff_reason") if value is not None else None

    @model_validator(mode="after")
    def enabled_has_reason(self):
        if self.enabled and self.reason is None:
            raise ValueError("handoff_reason_required_when_enabled")
        return self


class AssistantCalendarV1(StrictModel):
    provider: Literal["google_calendar", "wazza_native"]
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    business_hours: dict[str, list[dict[str, str]]] | None = None
    resource_name: str | None = Field(default=None, min_length=1, max_length=160)

    @model_validator(mode="after")
    def validate_native_schedule(self):
        if self.provider == "wazza_native":
            if not self.timezone or self.business_hours is None:
                raise ValueError("native_calendar_schedule_required")
            try:
                ZoneInfo(self.timezone)
            except ZoneInfoNotFoundError as exc:
                raise ValueError("invalid_calendar_timezone") from exc
            allowed = {"monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"}
            if set(self.business_hours) - allowed:
                raise ValueError("invalid_business_hours_day")
            for periods in self.business_hours.values():
                for period in periods:
                    if set(period) != {"start", "end"} or not re.fullmatch(r"\d{2}:\d{2}", period["start"]) or not re.fullmatch(r"\d{2}:\d{2}", period["end"]):
                        raise ValueError("invalid_business_hours")
                    if period["start"] >= period["end"]:
                        raise ValueError("invalid_business_hours")
        return self


class AssistantConfigurationV1(StrictModel):
    schema_version: Literal[1]
    clinic_name: str = Field(min_length=2, max_length=160)
    services: list[AssistantServiceV1] = Field(min_length=1, max_length=50)
    # Kept for legacy clients. An explicit calendar binding is authoritative.
    google_calendar_connection_id: UUID | None = None
    calendar: AssistantCalendarV1 | None = None
    handoff: AssistantHandoffV1

    @field_validator("clinic_name")
    @classmethod
    def validate_clinic_name(cls, value: str) -> str:
        value = _plain_text(value, "clinic_name")
        if len(value) < 2:
            raise ValueError("clinic_name_too_short")
        return value

    @model_validator(mode="after")
    def unique_service_ids(self):
        ids = [service.id for service in self.services]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_service_id")
        if self.calendar is None:
            if self.google_calendar_connection_id is None:
                raise ValueError("calendar_binding_required")
        elif self.calendar.provider == "google_calendar":
            if self.google_calendar_connection_id is None:
                raise ValueError("google_calendar_connection_required")
        elif self.google_calendar_connection_id is not None:
            raise ValueError("hybrid_calendar_binding_not_allowed")
        return self

    @property
    def effective_calendar_provider(self) -> str:
        return self.calendar.provider if self.calendar is not None else "google_calendar"


class AssistantConfigurationUpdate(StrictModel):
    expected_configuration_version: int = Field(ge=0, strict=True)
    configuration: AssistantConfigurationV1


class AssistantMaterializationRequest(StrictModel):
    expected_configuration_version: int = Field(ge=1, strict=True)
    expected_managed_flow_version_id: UUID | None


class AssistantActivationRequest(StrictModel):
    expected_configuration_version: int = Field(ge=1, strict=True)
    expected_managed_flow_version_id: UUID | None
    confirm_replace_active_flow: bool = Field(default=False, strict=True)


class AssistantFlowManagementResponse(StrictModel):
    mode: Literal["managed", "customized", "unknown", "inconsistent"]
    flow_id: UUID | None
    managed_flow_version_id: UUID | None
    current_flow_version_id: UUID | None
    has_drift: bool | None


class AssistantMaterializationResponse(StrictModel):
    installation_id: UUID
    flow_id: UUID
    configuration_version: int
    materialized: bool
    reason: Literal["materialized", "already_up_to_date"]
    flow_version_id: UUID
    management: AssistantFlowManagementResponse


class AssistantActivationResponse(StrictModel):
    installation_id: UUID
    flow_id: UUID
    configuration_version: int
    flow_version_id: UUID
    published_version_id: UUID
    active: bool
    already_active: bool
    replaced_active_flow_id: UUID | None
    management: AssistantFlowManagementResponse


class AssistantConfigurationResponse(StrictModel):
    installation_id: UUID
    status: Literal["configured", "needs_configuration"]
    configuration_version: int
    configuration: AssistantConfigurationV1 | None
    updated_at: datetime | None
    updated_by: UUID | None
    management: AssistantFlowManagementResponse


class ConfiguratorService(StrictModel):
    id: str
    label: str
    duration_minutes: int


class ConfiguratorHandoff(StrictModel):
    enabled: bool
    reason: str | None


class ConfiguratorConfiguration(StrictModel):
    status: Literal["configured", "needs_configuration"]
    version: int
    clinic_name: str | None
    services: list[ConfiguratorService]
    handoff: ConfiguratorHandoff | None


class ConfiguratorAssistant(StrictModel):
    type: Literal["appointment"]
    template_id: str
    template_version_id: UUID | None
    flow_id: UUID | None
    flow_name: str | None
    status: Literal["needs_configuration", "ready_to_activate", "active", "changes_pending", "customized", "integration_error", "configuration_error"]


class ConfiguratorCalendar(StrictModel):
    connection_id: UUID | None
    status: Literal["connected", "inactive", "missing", "not_configured"]
    provider: Literal["google_calendar", "wazza_native"]
    binding_id: UUID | None = None
    native_calendar_id: UUID | None = None
    native_resource_id: UUID | None = None
    available_connections: list["ConfiguratorCalendarConnection"]


class ConfiguratorCalendarConnection(StrictModel):
    id: UUID
    status: Literal["active"]
    label: str


class ConfiguratorScheduling(StrictModel):
    scope: Literal["workspace"]
    timezone: str
    business_hours: dict[str, list[dict[str, str]]]
    slot_interval_minutes: int
    default_duration_minutes: int


class ConfiguratorManagement(StrictModel):
    mode: Literal["managed", "customized", "unknown", "inconsistent"]
    has_drift: bool | None


class ConfiguratorActivation(StrictModel):
    active: bool
    up_to_date: bool
    needs_activation: bool
    would_replace_active_flow: bool


class ConfiguratorActions(StrictModel):
    can_edit: bool
    can_activate: bool
    can_open_builder: bool


class ConfiguratorConcurrency(StrictModel):
    configuration_version: int
    managed_flow_version_id: UUID | None


class ConfiguratorNotice(StrictModel):
    code: Literal["assistant_configuration_required", "assistant_flow_customized", "assistant_calendar_connection_required", "assistant_calendar_connection_inactive", "assistant_management_unknown", "assistant_management_inconsistent", "assistant_activation_required", "assistant_appointment_policy_invalid"]
    severity: Literal["info", "warning", "error"]


class AssistantConfiguratorResponse(StrictModel):
    installation_id: UUID
    assistant: ConfiguratorAssistant
    configuration: ConfiguratorConfiguration
    calendar: ConfiguratorCalendar
    scheduling: ConfiguratorScheduling | None
    management: ConfiguratorManagement
    activation: ConfiguratorActivation
    actions: ConfiguratorActions
    concurrency: ConfiguratorConcurrency
    notices: list[ConfiguratorNotice]
