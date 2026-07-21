from fastapi import APIRouter, Depends, HTTPException, Path, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import get_db
from app.models import Plan, PlanFeature, Subscription, Tenant, TenantUser
from app.routers.account import get_current_user
from app.services.audit_service import write_audit_log
from app.services.entitlement_service import EntitlementService
from app.services.tenant_service import get_current_tenant
from app.services.trial_service import TrialService

router = APIRouter(prefix="/billing", tags=["billing"])
admin_router = APIRouter(prefix="/admin/billing", tags=["admin-billing"])

def _plan(plan: Plan, features: list[PlanFeature] | None = None) -> dict:
    return {"code": plan.code, "name": plan.name, "description": plan.description, "monthly_price_cents": plan.monthly_price_cents, "annual_price_cents": plan.annual_price_cents, "currency": plan.currency, "features": [{"feature_key": f.feature_key, "enabled": f.enabled, "limit_value": f.limit_value, "limit_unit": f.limit_unit} for f in features or []]}

@router.get("/plans")
def public_plans(db: Session = Depends(get_db), user: TenantUser = Depends(get_current_user)):
    plans = db.execute(select(Plan).where(Plan.is_active.is_(True), Plan.is_public.is_(True)).order_by(Plan.sort_order)).scalars().all()
    return [_plan(plan, db.execute(select(PlanFeature).where(PlanFeature.plan_id == plan.id)).scalars().all()) for plan in plans]

@router.get("/current")
def current_billing(request: Request, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(get_current_user)):
    trial_service = TrialService(db)
    trial_service.expire_trial(tenant.id)
    subscription = db.execute(select(Subscription).where(Subscription.tenant_id == tenant.id)).scalars().first()
    plan = db.get(Plan, subscription.plan_id) if subscription else None
    service = EntitlementService(db)
    write_audit_log(db, action="BILLING_CURRENT_VIEWED", tenant_id=tenant.id, user_id=user.id, entity_type="subscription", entity_id=subscription.id if subscription else None, request=request)
    db.commit()
    is_trial = trial_service.is_trial(tenant.id)
    return {"tenant_id": str(tenant.id), "plan": _plan(plan, db.execute(select(PlanFeature).where(PlanFeature.plan_id == plan.id)).scalars().all()) if plan else None, "subscription": None if not subscription else {"status": subscription.status, "provider": subscription.provider, "billing_interval": subscription.billing_interval, "trial_started_at": subscription.trial_started_at, "trial_ends_at": subscription.trial_ends_at, "current_period_end": subscription.current_period_end}, "trial": is_trial, "days_remaining": trial_service.days_remaining(tenant.id), "expired": bool(subscription and subscription.status == "expired"), "effective_entitlements": list(service.get_effective_entitlements(tenant.id).values()), "enforcement_enabled": settings.billing_enforcement_enabled, "billing_ui_enabled": settings.billing_ui_enabled}

@router.get("/trial")
def trial_billing(request: Request, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(get_current_user)):
    service = TrialService(db)
    subscription = service.expire_trial(tenant.id)
    plan = db.get(Plan, subscription.plan_id) if subscription else None
    write_audit_log(db, action="TRIAL_VIEWED", tenant_id=tenant.id, user_id=user.id, entity_type="subscription", entity_id=subscription.id if subscription else None, request=request)
    db.commit()
    return {"status": subscription.status if subscription else "legacy", "days_remaining": service.days_remaining(tenant.id), "trial_started_at": subscription.trial_started_at if subscription else None, "trial_ends_at": subscription.trial_ends_at if subscription else None, "plan": plan.code if plan else None, "expired": bool(subscription and subscription.status == "expired")}

def _admin(user: TenantUser = Depends(get_current_user)) -> TenantUser:
    if user.role not in {"owner", "admin"}: raise HTTPException(status_code=403, detail="Acesso administrativo necessário")
    return user

@admin_router.get("/plans")
def admin_plans(db: Session = Depends(get_db), user: TenantUser = Depends(_admin)):
    return [_plan(plan, db.execute(select(PlanFeature).where(PlanFeature.plan_id == plan.id)).scalars().all()) for plan in db.execute(select(Plan).order_by(Plan.sort_order)).scalars().all()]

@admin_router.get("/tenants/{tenant_id}")
def admin_tenant_billing(tenant_id: str = Path(...), db: Session = Depends(get_db), user: TenantUser = Depends(_admin)):
    tenant = db.get(Tenant, tenant_id)
    if not tenant: raise HTTPException(status_code=404, detail="Tenant não encontrado")
    subscription = db.execute(select(Subscription).where(Subscription.tenant_id == tenant.id)).scalars().first()
    return {"tenant_id": str(tenant.id), "subscription_status": subscription.status if subscription else None, "effective_entitlements": list(EntitlementService(db).get_effective_entitlements(tenant.id).values())}
