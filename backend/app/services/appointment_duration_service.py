"""Resolve an appointment duration from server-owned assistant provenance.

The runtime may carry a logical service id, but never a duration.  Legacy and
unmanaged flows deliberately retain the tenant policy default.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import ValidationError
from sqlalchemy import select

from app.models import Flow
from app.models.marketplace_installation import (
    MarketplaceInstallation,
    MarketplaceInstallationAssistantConfiguration,
    MarketplaceInstallationFlowManagement,
    MarketplaceInstallationResource,
)
from app.schemas.assistant_configuration import AssistantConfigurationV1

SOURCE_ASSISTANT_SERVICE = "assistant_service"
SOURCE_TENANT_DEFAULT = "tenant_default"


class AppointmentDurationError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class EffectiveAppointmentDuration:
    duration_minutes: int
    source: str
    service_id: str | None = None


def _legacy(default_duration_minutes: int) -> EffectiveAppointmentDuration:
    return EffectiveAppointmentDuration(default_duration_minutes, SOURCE_TENANT_DEFAULT)


def resolve_effective_appointment_duration(
    db: Any,
    *,
    tenant_id: Any,
    flow_id: Any | None,
    flow_version_id: Any | None,
    runtime_variables: dict[str, Any] | None,
    default_duration_minutes: int,
) -> EffectiveAppointmentDuration:
    """Resolve once per tool call, constrained by tenant, flow and provenance.

    Absence of managed provenance is a legacy flow. Ambiguous or malformed
    managed provenance fails closed rather than selecting an arbitrary record.
    Customized/drifted flows use the legacy default because their declared
    Choice binding can no longer be trusted.
    """
    if flow_id is None:
        return _legacy(default_duration_minutes)

    rows = db.execute(
        select(
            MarketplaceInstallation,
            MarketplaceInstallationAssistantConfiguration,
            MarketplaceInstallationFlowManagement,
            Flow,
        )
        .join(
            MarketplaceInstallationResource,
            MarketplaceInstallationResource.installation_id == MarketplaceInstallation.id,
        )
        .join(Flow, Flow.id == flow_id)
        .outerjoin(
            MarketplaceInstallationAssistantConfiguration,
            MarketplaceInstallationAssistantConfiguration.installation_id == MarketplaceInstallation.id,
        )
        .outerjoin(
            MarketplaceInstallationFlowManagement,
            MarketplaceInstallationFlowManagement.installation_id == MarketplaceInstallation.id,
        )
        .where(
            MarketplaceInstallation.tenant_id == tenant_id,
            Flow.tenant_id == tenant_id,
            MarketplaceInstallationResource.resource_type == "flow",
            MarketplaceInstallationResource.resource_id == str(flow_id),
        )
    ).all()
    if not rows:
        return _legacy(default_duration_minutes)
    if len(rows) != 1:
        raise AppointmentDurationError("assistant_configuration_invalid")

    installation, configuration_row, management, _flow = rows[0]
    if configuration_row is None:
        return _legacy(default_duration_minutes)
    if (
        management is None
        or management.management_mode != "managed"
        or flow_version_id is None
        or management.managed_flow_version_id != flow_version_id
    ):
        return _legacy(default_duration_minutes)

    contract = (installation.manifest_snapshot or {}).get("assistant_materialization")
    variable = contract.get("service_selection_variable") if isinstance(contract, dict) else None
    if not isinstance(contract, dict) or contract.get("schema_version") != 1:
        return _legacy(default_duration_minutes)
    if not isinstance(variable, str) or not variable.strip():
        return _legacy(default_duration_minutes)

    try:
        configuration = AssistantConfigurationV1.model_validate(configuration_row.configuration)
    except ValidationError as exc:
        raise AppointmentDurationError("assistant_configuration_invalid") from exc

    service_id = (runtime_variables or {}).get(variable)
    if not isinstance(service_id, str) or not service_id:
        raise AppointmentDurationError("assistant_service_not_selected")
    matches = [service for service in configuration.services if service.id == service_id]
    if len(matches) != 1:
        raise AppointmentDurationError("assistant_service_not_found")
    return EffectiveAppointmentDuration(matches[0].duration_minutes, SOURCE_ASSISTANT_SERVICE, service_id)
