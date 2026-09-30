from __future__ import annotations

from datetime import datetime
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.marketplace_installation import (
    MarketplaceInstallation,
    MarketplaceInstallationAssistantConfiguration,
)
from app.models.user import TenantUser
from app.schemas.assistant_configuration import AssistantConfigurationUpdate
from app.services.audit_service import write_audit_log
from app.services.assistant_calendar_binding_service import bind_assistant_calendar

CAPABILITY = "appointment_assistant_configuration"
# These are server-owned built-in catalog identities, not values supplied by clients.
BUILTIN_APPOINTMENT_TEMPLATES = frozenset({"agenda_inteligente", "agendamento_simples", "agendamento_hibrido"})


def _capabilities(installation: MarketplaceInstallation) -> set[str]:
    manifest = installation.manifest_snapshot if isinstance(installation.manifest_snapshot, dict) else {}
    raw = manifest.get("capabilities", [])
    if isinstance(raw, str):
        raw = [raw]
    return {str(value) for value in raw} if isinstance(raw, list) else set()


def supports_assistant_configuration(installation: MarketplaceInstallation) -> bool:
    return CAPABILITY in _capabilities(installation) or installation.template_slug in BUILTIN_APPOINTMENT_TEMPLATES


def serialize_configuration(installation: MarketplaceInstallation, management: dict) -> dict:
    row = installation.assistant_configuration
    return {
        "installation_id": installation.id,
        "status": "configured" if row else "needs_configuration",
        "configuration_version": row.configuration_version if row else 0,
        "configuration": row.configuration if row else None,
        "updated_at": row.updated_at if row else None,
        "updated_by": row.updated_by_user_id if row else None,
        "management": management,
    }


def get_installation_for_configuration(db: Session, installation_id: UUID, tenant_id: UUID, *, lock: bool = False) -> MarketplaceInstallation:
    statement = select(MarketplaceInstallation).where(
        MarketplaceInstallation.id == installation_id,
        MarketplaceInstallation.tenant_id == tenant_id,
    )
    if lock:
        statement = statement.with_for_update()
    installation = db.scalar(statement)
    if installation is None:
        # Deliberately indistinguishable from a missing cross-tenant object.
        raise HTTPException(status_code=404, detail="installation_not_found")
    if not supports_assistant_configuration(installation):
        raise HTTPException(status_code=422, detail="template_does_not_support_assistant_configuration")
    return installation


def update_configuration(
    db: Session,
    *,
    installation_id: UUID,
    tenant_id: UUID,
    actor: TenantUser,
    payload: AssistantConfigurationUpdate,
    request: Request | None,
) -> MarketplaceInstallation:
    installation = get_installation_for_configuration(db, installation_id, tenant_id, lock=True)
    row = db.scalar(
        select(MarketplaceInstallationAssistantConfiguration)
        .where(MarketplaceInstallationAssistantConfiguration.installation_id == installation.id)
        .with_for_update()
    )
    current_version = row.configuration_version if row else 0
    if payload.expected_configuration_version != current_version:
        raise HTTPException(status_code=409, detail={
            "code": "assistant_configuration_version_conflict",
            "current_configuration_version": current_version,
        })

    bind_assistant_calendar(
        db, installation=installation, configuration=payload.configuration,
        actor_id=actor.id, request=request,
    )

    before = dict(row.configuration) if row else None
    after = payload.configuration.model_dump(mode="json")
    new_version = current_version + 1
    if row is None:
        row = MarketplaceInstallationAssistantConfiguration(
            installation_id=installation.id,
            configuration=after,
            configuration_version=new_version,
            updated_by_user_id=actor.id,
        )
        db.add(row)
        installation.assistant_configuration = row
    else:
        row.configuration = after
        row.configuration_version = new_version
        row.updated_by_user_id = actor.id
        row.updated_at = datetime.utcnow()

    changed_fields = sorted(
        key for key in after if before is None or before.get(key) != after.get(key)
    )
    flow_resource = next((r for r in installation.resources if r.resource_type == "flow"), None)
    resource_metadata = flow_resource.metadata_json if flow_resource and isinstance(flow_resource.metadata_json, dict) else {}
    write_audit_log(
        db,
        action="assistant_configuration_updated",
        tenant_id=tenant_id,
        user_id=actor.id,
        entity_type="marketplace_installation_assistant_configuration",
        entity_id=installation.id,
        metadata={
            "installation_id": installation.id,
            "flow_id": flow_resource.resource_id if flow_resource else None,
            "template_id": resource_metadata.get("template_id", installation.template_id),
            "template_version_id": resource_metadata.get("template_version_id"),
            "previous_configuration_version": current_version,
            "configuration_version": new_version,
            "changed_fields": changed_fields,
            "before": before,
            "after": after,
        },
        request=request,
    )
    db.commit()
    db.refresh(row)
    return installation
