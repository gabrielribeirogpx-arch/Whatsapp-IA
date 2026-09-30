"""Read-only, product-facing projection for the appointment configurator."""
from __future__ import annotations

from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import AuditLog, Flow
from app.models.integration_connection import IntegrationConnection
from app.models.marketplace_installation import AssistantCalendarBinding, MarketplaceInstallation
from app.models.native_calendar import CalendarResource, NativeCalendar
from app.models.user import TenantUser
from app.schemas.assistant_configuration import AssistantConfigurationV1
from app.security.workspace_rbac import PERMISSION_MATRIX, WorkspacePermission, canonical_role
from app.services.appointment_policy_service import AppointmentPolicyError, policy_for_tenant
from app.services.assistant_configuration_service import get_installation_for_configuration
from app.services.assistant_flow_management_service import inspect_flow_management


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _has_permissions(user: TenantUser, *permissions: WorkspacePermission) -> bool:
    role = canonical_role(user.role)
    return role is not None and all(permission in PERMISSION_MATRIX[role] for permission in permissions)


class AssistantConfiguratorService:
    """Compose a safe snapshot; this service intentionally never flushes or commits."""

    def __init__(self, db: Session):
        self.db = db

    def _available_calendar_connections(self, tenant_id: UUID) -> list[IntegrationConnection]:
        return list(self.db.scalars(select(IntegrationConnection).where(
            IntegrationConnection.tenant_id == tenant_id,
            IntegrationConnection.provider == "google_calendar",
            IntegrationConnection.status == "active",
        ).order_by(IntegrationConnection.created_at.asc(), IntegrationConnection.id.asc())).all())

    def read(self, *, installation_id: UUID, tenant_id: UUID, user: TenantUser) -> dict:
        installation = get_installation_for_configuration(self.db, installation_id, tenant_id)
        management = inspect_flow_management(self.db, installation=installation, tenant_id=tenant_id)
        flow = self.db.scalar(select(Flow).where(
            Flow.id == management.flow_id, Flow.tenant_id == tenant_id,
            Flow.is_deleted.is_(False), Flow.deleted_at.is_(None),
        )) if management.flow_id else None

        resource = next((item for item in installation.resources if item.resource_type == "flow"), None)
        provenance = resource.metadata_json if resource and isinstance(resource.metadata_json, dict) else {}
        template_version_id = _uuid(provenance.get("template_version_id"))

        row = installation.assistant_configuration
        configuration = None
        configuration_valid = False
        if row is not None:
            try:
                configuration = AssistantConfigurationV1.model_validate(row.configuration)
                configuration_valid = True
            except ValidationError:
                pass

        connection = None
        binding = self.db.scalar(select(AssistantCalendarBinding).where(
            AssistantCalendarBinding.installation_id == installation.id,
            AssistantCalendarBinding.tenant_id == tenant_id,
        ))
        calendar_status = "not_configured"
        available_connections = self._available_calendar_connections(tenant_id)
        provider = binding.provider if binding else (configuration.effective_calendar_provider if configuration else "wazza_native")
        connection_id = binding.integration_connection_id if binding else (
            configuration.google_calendar_connection_id if configuration else None)
        native_calendar_id = binding.native_calendar_id if binding else None
        native_resource_id = binding.native_resource_id if binding else None
        if provider == "google_calendar" and connection_id:
            connection = self.db.scalar(select(IntegrationConnection).where(
                IntegrationConnection.id == connection_id,
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.provider == "google_calendar",
            ))
            calendar_status = "missing" if connection is None else ("connected" if connection.status == "active" else "inactive")
        elif provider == "wazza_native" and binding:
            native_calendar = self.db.scalar(select(NativeCalendar).where(
                NativeCalendar.id == native_calendar_id, NativeCalendar.tenant_id == tenant_id,
            ))
            native_resource = self.db.scalar(select(CalendarResource).where(
                CalendarResource.id == native_resource_id, CalendarResource.tenant_id == tenant_id,
                CalendarResource.calendar_id == native_calendar_id,
            ))
            calendar_status = "connected" if native_calendar and native_resource and native_calendar.active and native_resource.active else "missing"

        scheduling = None
        policy_valid = True
        try:
            policy = policy_for_tenant(self.db, tenant_id)
            scheduling = {
                "scope": "workspace", "timezone": policy["timezone"],
                "business_hours": policy["business_hours"],
                "slot_interval_minutes": policy["slot_interval_minutes"],
                "default_duration_minutes": policy["default_duration_minutes"],
            }
        except AppointmentPolicyError:
            policy_valid = False

        active = bool(flow and flow.is_active)
        up_to_date = self._activation_is_proven(
            installation, flow, row.configuration_version if row else 0,
        )
        needs_activation = bool(configuration_valid and (not active or not up_to_date))
        another_active = self.db.scalar(select(Flow.id).where(
            Flow.tenant_id == tenant_id, Flow.is_active.is_(True),
            Flow.is_deleted.is_(False), Flow.deleted_at.is_(None),
            Flow.id != flow.id if flow else Flow.id.is_not(None),
        ).limit(1))

        status, notices = self._status_and_notices(
            configured=row is not None, configuration_valid=configuration_valid,
            management_mode=management.mode, calendar_status=calendar_status,
            policy_valid=policy_valid, active=active, up_to_date=up_to_date,
        )
        may_activate = _has_permissions(
            user, WorkspacePermission.MANAGE_SETTINGS, WorkspacePermission.MANAGE_FLOWS,
            WorkspacePermission.PUBLISH_FLOWS, WorkspacePermission.ACTIVATE_FLOWS,
        )
        can_activate = bool(
            may_activate and configuration_valid and policy_valid
            and calendar_status == "connected" and management.mode == "managed"
        )
        return {
            "installation_id": installation.id,
            "assistant": {
                "type": "appointment", "template_id": installation.template_id,
                "template_version_id": template_version_id,
                "flow_id": flow.id if flow else management.flow_id,
                "flow_name": flow.name if flow else None, "status": status,
            },
            "configuration": {
                "status": "configured" if configuration_valid else "needs_configuration",
                "version": row.configuration_version if row else 0,
                "clinic_name": configuration.clinic_name if configuration else None,
                "services": [service.model_dump() for service in configuration.services] if configuration else [],
                "handoff": configuration.handoff.model_dump() if configuration else None,
            },
            "calendar": {
                "connection_id": connection_id,
                "status": calendar_status,
                "provider": provider,
                "binding_id": binding.id if binding else None,
                "native_calendar_id": native_calendar_id,
                "native_resource_id": native_resource_id,
                "available_connections": [
                    {
                        "id": item.id,
                        "status": "active",
                        "label": (
                            item.metadata_json.get("account_email")
                            if isinstance(item.metadata_json, dict) and item.metadata_json.get("account_email")
                            else "Google Calendar"
                        ),
                    }
                    for item in available_connections
                ],
            },
            "scheduling": scheduling,
            "management": {"mode": management.mode, "has_drift": management.has_drift},
            "activation": {
                "active": active, "up_to_date": up_to_date,
                "needs_activation": needs_activation,
                "would_replace_active_flow": another_active is not None,
            },
            "actions": {
                "can_edit": _has_permissions(user, WorkspacePermission.MANAGE_SETTINGS),
                "can_activate": can_activate,
                "can_open_builder": _has_permissions(user, WorkspacePermission.VIEW_FLOWS) and flow is not None,
            },
            "concurrency": {
                "configuration_version": row.configuration_version if row else 0,
                "managed_flow_version_id": management.managed_flow_version_id,
            },
            "notices": notices,
        }

    def _activation_is_proven(self, installation: MarketplaceInstallation, flow: Flow | None, configuration_version: int) -> bool:
        if not flow or not flow.is_active or flow.published_version_id is None or configuration_version < 1:
            return False
        audits = self.db.scalars(select(AuditLog).where(
            AuditLog.tenant_id == installation.tenant_id,
            AuditLog.entity_id == str(installation.id),
            AuditLog.action.in_(("assistant_activated", "assistant_activation_confirmed")),
        )).all()
        for audit in audits:
            metadata = audit.metadata_json if isinstance(audit.metadata_json, dict) else {}
            if (str(metadata.get("installation_id")) == str(installation.id)
                    and str(metadata.get("flow_id")) == str(flow.id)
                    and metadata.get("configuration_version") == configuration_version
                    and str(metadata.get("flow_version_id")) == str(flow.published_version_id)):
                return True
        return False

    @staticmethod
    def _status_and_notices(*, configured: bool, configuration_valid: bool, management_mode: str,
                            calendar_status: str, policy_valid: bool, active: bool,
                            up_to_date: bool) -> tuple[str, list[dict[str, str]]]:
        notices: list[dict[str, str]] = []
        if not configured:
            return "needs_configuration", [{"code": "assistant_configuration_required", "severity": "warning"}]
        if not configuration_valid:
            return "configuration_error", [{"code": "assistant_configuration_required", "severity": "error"}]
        if management_mode == "customized":
            return "customized", [{"code": "assistant_flow_customized", "severity": "warning"}]
        if management_mode in {"unknown", "inconsistent"}:
            code = f"assistant_management_{management_mode}"
            return "configuration_error", [{"code": code, "severity": "error"}]
        if calendar_status != "connected":
            code = "assistant_calendar_connection_inactive" if calendar_status == "inactive" else "assistant_calendar_connection_required"
            return "integration_error", [{"code": code, "severity": "error"}]
        if not policy_valid:
            return "configuration_error", [{"code": "assistant_appointment_policy_invalid", "severity": "error"}]
        if active and up_to_date:
            return "active", notices
        notices.append({"code": "assistant_activation_required", "severity": "warning"})
        return ("changes_pending" if active else "ready_to_activate"), notices
