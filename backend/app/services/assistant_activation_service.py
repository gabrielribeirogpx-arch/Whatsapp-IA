"""Safe configure -> materialize -> exact publish -> activate orchestration."""
from __future__ import annotations

from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Flow, FlowVersion
from app.schemas.assistant_configuration import (
    AssistantActivationRequest,
    AssistantMaterializationRequest,
)
from app.services.appointment_policy_service import AppointmentPolicyError, policy_for_tenant
from app.services.assistant_configuration_service import get_installation_for_configuration
from app.services.assistant_materialization_service import materialize_configuration
from app.services.audit_service import write_audit_log
from app.services.cache_service import invalidate_tenant_and_flow_cache
from app.services.flow_activation_service import (
    acquire_tenant_flow_activation_lock,
    activate_flow_exclusively,
    find_active_flows,
)
from app.services.flow_engine_service import invalidate_flow_runtime_cache
from app.services.flow_service import FlowService


def activate_assistant_configuration(
    db: Session, *, installation_id: UUID, tenant_id: UUID, actor_id: UUID,
    payload: AssistantActivationRequest, request: Request | None,
) -> dict:
    """Execute the complete pipeline in the caller's single DB transaction."""
    try:
        acquire_tenant_flow_activation_lock(db, tenant_id)
        installation = get_installation_for_configuration(db, installation_id, tenant_id, lock=True)
        management = installation.flow_management
        flow_id = management.flow_id if management else None
        flow = db.scalar(select(Flow).where(
            Flow.id == flow_id, Flow.tenant_id == tenant_id,
            Flow.is_deleted.is_(False), Flow.deleted_at.is_(None),
        ).with_for_update()) if flow_id else None
        if flow is None:
            raise HTTPException(409, {"code": "assistant_flow_customized"})

        other_active = next((item for item in find_active_flows(db, tenant_id) if item.id != flow.id), None)
        if other_active is not None and not payload.confirm_replace_active_flow:
            raise HTTPException(409, {
                "code": "assistant_activation_would_replace_active_flow",
                "active_flow_id": str(other_active.id),
            })

        # This canonical reader also validates timezone and business-hour policy.
        try:
            policy_for_tenant(db, tenant_id)
        except AppointmentPolicyError as exc:
            raise HTTPException(422, {"code": "assistant_appointment_policy_invalid"}) from exc

        result = materialize_configuration(
            db, installation_id=installation_id, tenant_id=tenant_id, actor_id=actor_id,
            payload=AssistantMaterializationRequest(
                expected_configuration_version=payload.expected_configuration_version,
                expected_managed_flow_version_id=payload.expected_managed_flow_version_id,
            ), request=request, commit=False,
        )
        target_id = result["flow_version_id"]
        db.refresh(flow)
        if flow.current_version_id != target_id:
            raise HTTPException(409, {"code": "assistant_activation_conflict"})
        target = db.scalar(select(FlowVersion).where(
            FlowVersion.id == target_id, FlowVersion.flow_id == flow.id,
            FlowVersion.tenant_id == tenant_id,
        ).with_for_update())
        if target is None:
            raise HTTPException(409, {"code": "assistant_activation_conflict"})

        already_active = bool(flow.is_active and flow.published_version_id == target.id)
        if not already_active:
            if flow.published_version_id != target.id or not target.is_published:
                try:
                    FlowService(db).publish_exact_version(flow, target)
                except Exception as exc:
                    raise HTTPException(422, {"code": "assistant_publish_failed"}) from exc
                management.managed_graph_checksum = target.graph_checksum
            if flow.published_version_id != target.id:
                raise HTTPException(409, {"code": "assistant_activation_conflict"})
            activate_flow_exclusively(db=db, tenant_id=tenant_id, flow=flow)
            if not flow.is_active or flow.published_version_id != target.id:
                raise HTTPException(409, {"code": "assistant_activation_conflict"})
        # This explicit association is also written for an idempotent activation.
        # It is the durable proof that the current configuration was accepted for
        # the exact published version; the configurator never guesses by timestamp.
        metadata = next((r.metadata_json for r in installation.resources if r.resource_type == "flow"), {}) or {}
        write_audit_log(
            db, action="assistant_activation_confirmed" if already_active else "assistant_activated",
            tenant_id=tenant_id, user_id=actor_id,
            entity_type="marketplace_installation", entity_id=installation.id,
            metadata={
                "installation_id": installation.id, "flow_id": flow.id,
                "template_id": metadata.get("template_id", installation.template_id),
                "template_version_id": metadata.get("template_version_id"),
                "configuration_version": payload.expected_configuration_version,
                "flow_version_id": target.id,
                "replaced_active_flow_id": other_active.id if other_active else None,
            }, request=request,
        )

        db.commit()
        invalidate_flow_runtime_cache(flow.id)
        invalidate_tenant_and_flow_cache(str(tenant_id))
        return {
            "installation_id": installation.id, "flow_id": flow.id,
            "configuration_version": payload.expected_configuration_version,
            "flow_version_id": target.id, "published_version_id": target.id,
            "active": True, "already_active": already_active,
            "replaced_active_flow_id": other_active.id if other_active and not already_active else None,
            "management": {
                "mode": "managed", "flow_id": flow.id,
                "managed_flow_version_id": target.id,
                "current_flow_version_id": target.id, "has_drift": False,
            },
        }
    except Exception:
        db.rollback()
        raise
