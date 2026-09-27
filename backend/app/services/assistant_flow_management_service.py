"""Managed-baseline and structural-drift checks for configured assistants.

This module never writes Flow graph data or creates FlowVersion rows.  The only
writes made while checking are the management row and the first drift audit.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.flow import Flow, FlowVersion
from app.models.marketplace_installation import (
    MarketplaceInstallation,
    MarketplaceInstallationFlowManagement,
    MarketplaceInstallationResource,
)
from app.services.audit_service import write_audit_log


@dataclass(frozen=True)
class FlowManagementState:
    mode: str
    flow_id: UUID | None
    managed_flow_version_id: UUID | None
    current_flow_version_id: UUID | None
    has_drift: bool | None

    def public_dict(self) -> dict:
        return {
            "mode": self.mode,
            "flow_id": self.flow_id,
            "managed_flow_version_id": self.managed_flow_version_id,
            "current_flow_version_id": self.current_flow_version_id,
            "has_drift": self.has_drift,
        }


def _uuid(value) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _valid_checksum(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _flow_resource(installation: MarketplaceInstallation) -> MarketplaceInstallationResource | None:
    matches = [resource for resource in installation.resources if resource.resource_type == "flow"]
    return matches[0] if len(matches) == 1 else None


def _load_version(db: Session, version_id: UUID | None, flow: Flow, tenant_id: UUID) -> FlowVersion | None:
    if version_id is None:
        return None
    return db.scalar(select(FlowVersion).where(
        FlowVersion.id == version_id,
        FlowVersion.flow_id == flow.id,
        FlowVersion.tenant_id == tenant_id,
    ))


def establish_official_baseline(
    db: Session, *, installation: MarketplaceInstallation, flow: Flow,
    flow_version: FlowVersion, checksum: str,
) -> MarketplaceInstallationFlowManagement:
    """Establish baseline only from the just-created, tenant-scoped version."""
    if (flow.tenant_id != installation.tenant_id or flow_version.flow_id != flow.id
            or flow_version.tenant_id != installation.tenant_id
            or flow.current_version_id != flow_version.id
            or not _valid_checksum(checksum) or flow_version.graph_checksum != checksum):
        raise ValueError("invalid_managed_flow_baseline")
    row = MarketplaceInstallationFlowManagement(
        installation_id=installation.id, flow_id=flow.id, management_mode="managed",
        managed_flow_version_id=flow_version.id, managed_graph_checksum=checksum,
    )
    db.add(row)
    installation.flow_management = row
    return row


def detect_flow_drift(
    db: Session, *, installation: MarketplaceInstallation, tenant_id: UUID,
    actor_id: UUID | None = None, request: Request | None = None, lock: bool = False,
) -> FlowManagementState:
    """Resolve and persist fail-closed state; equal checksums advance the baseline."""
    if installation.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="installation_not_found")
    resource = _flow_resource(installation)
    flow_id = _uuid(resource.resource_id) if resource else None
    if flow_id is None:
        return FlowManagementState("unknown", None, None, None, None)
    query = select(Flow).where(Flow.id == flow_id, Flow.tenant_id == tenant_id)
    # Detection can advance an equivalent baseline, so the Flow is always
    # locked.  ``lock`` remains explicit in the concurrency primitive's API to
    # document the stronger expected-version operation.
    query = query.with_for_update()
    flow = db.scalar(query)
    if flow is None:
        return FlowManagementState("unknown", flow_id, None, None, None)

    row = db.scalar(select(MarketplaceInstallationFlowManagement).where(
        MarketplaceInstallationFlowManagement.installation_id == installation.id,
        MarketplaceInstallationFlowManagement.flow_id == flow.id,
    ).with_for_update())
    if row is None:
        # Safe legacy initialization: exact official provenance, unchanged current
        # version, and an existing canonical checksum are all mandatory.
        metadata = resource.metadata_json if isinstance(resource.metadata_json, dict) else {}
        generated_id = _uuid(metadata.get("generated_flow_version_id"))
        template_version_id = _uuid(metadata.get("template_version_id"))
        generated = _load_version(db, generated_id, flow, tenant_id)
        if template_version_id and generated and flow.current_version_id == generated.id and _valid_checksum(generated.graph_checksum):
            row = MarketplaceInstallationFlowManagement(
                installation_id=installation.id, flow_id=flow.id, management_mode="managed",
                managed_flow_version_id=generated.id, managed_graph_checksum=generated.graph_checksum,
            )
            db.add(row)
            installation.flow_management = row
        else:
            return FlowManagementState("unknown", flow.id, None, flow.current_version_id, None)

    baseline = _load_version(db, row.managed_flow_version_id, flow, tenant_id)
    current = _load_version(db, flow.current_version_id, flow, tenant_id)
    if (baseline is None or not _valid_checksum(row.managed_graph_checksum)
            or baseline.graph_checksum != row.managed_graph_checksum
            or current is None or not _valid_checksum(current.graph_checksum)):
        row.management_mode = "inconsistent"
        row.updated_at = datetime.utcnow()
        return FlowManagementState("inconsistent", flow.id, row.managed_flow_version_id, flow.current_version_id, None)

    drift = current.graph_checksum != row.managed_graph_checksum
    if not drift:
        row.management_mode = "managed"
        if current.id != row.managed_flow_version_id:
            row.managed_flow_version_id = current.id
            row.managed_graph_checksum = current.graph_checksum
        row.updated_at = datetime.utcnow()
        return FlowManagementState("managed", flow.id, row.managed_flow_version_id, current.id, False)

    first_transition = row.management_mode != "customized"
    row.management_mode = "customized"
    row.updated_at = datetime.utcnow()
    if first_transition:
        metadata = resource.metadata_json if isinstance(resource.metadata_json, dict) else {}
        write_audit_log(
            db, action="assistant_marked_customized", tenant_id=tenant_id, user_id=actor_id,
            entity_type="marketplace_installation_flow_management", entity_id=installation.id,
            metadata={
                "installation_id": installation.id, "flow_id": flow.id,
                "managed_flow_version_id": row.managed_flow_version_id,
                "current_flow_version_id": current.id,
                "managed_graph_checksum": row.managed_graph_checksum,
                "current_graph_checksum": current.graph_checksum,
                "template_version_id": metadata.get("template_version_id"),
            }, request=request,
        )
    return FlowManagementState("customized", flow.id, row.managed_flow_version_id, current.id, True)


def assert_managed_flow_baseline(
    db: Session, *, installation: MarketplaceInstallation, tenant_id: UUID,
    expected_managed_flow_version_id: UUID,
) -> FlowManagementState:
    """Concurrency primitive for a future materializer; locks before comparing."""
    state = detect_flow_drift(db, installation=installation, tenant_id=tenant_id, lock=True)
    if state.mode != "managed" or state.managed_flow_version_id != expected_managed_flow_version_id:
        raise HTTPException(status_code=409, detail={
            "code": "managed_flow_version_conflict",
            "current_managed_flow_version_id": str(state.managed_flow_version_id) if state.managed_flow_version_id else None,
            "management_mode": state.mode,
        })
    return state
