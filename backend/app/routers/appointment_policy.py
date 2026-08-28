from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.tenant import Tenant
from app.models.tenant_appointment_policy import TenantAppointmentPolicy
from app.schemas.appointment_policy import AppointmentPolicyOut, AppointmentPolicyUpdate
from app.services.appointment_policy_service import AppointmentPolicyError, policy_for_tenant, validate_policy
from app.services.tenant_service import get_current_tenant
router=APIRouter(prefix="/appointment-policy", tags=["appointment-policy"])
@router.get("", response_model=AppointmentPolicyOut)
def get_policy(tenant: Tenant=Depends(get_current_tenant), db: Session=Depends(get_db)):
    return policy_for_tenant(db, tenant.id)
@router.put("", response_model=AppointmentPolicyOut)
def put_policy(payload: AppointmentPolicyUpdate, tenant: Tenant=Depends(get_current_tenant), db: Session=Depends(get_db)):
    try: policy=validate_policy(payload.model_dump())
    except AppointmentPolicyError as exc: raise HTTPException(400, detail=str(exc)) from exc
    item=db.query(TenantAppointmentPolicy).filter(TenantAppointmentPolicy.tenant_id==tenant.id).one_or_none()
    if not item: item=TenantAppointmentPolicy(tenant_id=tenant.id); db.add(item)
    item.policy_json=policy; db.commit(); return policy
