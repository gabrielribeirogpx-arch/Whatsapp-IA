from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tenant import Tenant
from app.models.tenant_appointment_policy import TenantAppointmentPolicy
from app.models.user import TenantUser
from app.routers.account import get_current_user
from app.schemas.appointment_policy import AppointmentPolicyOut, AppointmentPolicyUpdate
from app.security.workspace_rbac import WorkspacePermission
from app.services.administrative_audit import require_administrative_permission
from app.services.appointment_policy_service import AppointmentPolicyError, policy_for_tenant, validate_policy
from app.services.audit_service import write_audit_log
from app.services.tenant_service import get_current_tenant

router = APIRouter(prefix="/appointment-policy", tags=["appointment-policy"])


@router.get("", response_model=AppointmentPolicyOut)
def get_policy(
    request: Request,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    current_user: TenantUser = Depends(get_current_user),
):
    # The policy is non-secret Flow/assistant configuration. V1 therefore uses
    # VIEW_FLOWS, which intentionally includes member and viewer read access.
    require_administrative_permission(
        db, current_user, WorkspacePermission.VIEW_FLOWS,
        request=request, action="appointment_policy_viewed",
        resource_type="tenant_appointment_policy", resource_id=tenant.id,
    )
    return policy_for_tenant(db, tenant.id)


@router.put("", response_model=AppointmentPolicyOut)
def put_policy(
    payload: AppointmentPolicyUpdate,
    request: Request,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    current_user: TenantUser = Depends(get_current_user),
):
    require_administrative_permission(
        db, current_user, WorkspacePermission.MANAGE_SETTINGS,
        request=request, action="appointment_policy_updated",
        resource_type="tenant_appointment_policy", resource_id=tenant.id,
    )
    try:
        policy = validate_policy(payload.model_dump())
    except AppointmentPolicyError as exc:
        raise HTTPException(400, detail=str(exc)) from exc

    item = db.query(TenantAppointmentPolicy).filter(
        TenantAppointmentPolicy.tenant_id == tenant.id
    ).one_or_none()
    before = dict(item.policy_json or {}) if item else {}
    if not item:
        item = TenantAppointmentPolicy(tenant_id=tenant.id)
        db.add(item)
    item.policy_json = policy
    changed_fields = sorted(key for key in policy if before.get(key) != policy.get(key))
    write_audit_log(
        db,
        action="appointment_policy_updated",
        tenant_id=tenant.id,
        user_id=current_user.id,
        entity_type="tenant_appointment_policy",
        entity_id=tenant.id,
        metadata={"changed_fields": changed_fields, "before": before, "after": policy},
        request=request,
    )
    db.commit()
    return policy
