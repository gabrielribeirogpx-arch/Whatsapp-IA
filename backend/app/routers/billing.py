import hashlib
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.database import get_db
from app.billing.stripe_provider import StripeBillingProvider
from app.billing.stripe_webhook_service import StripeWebhookService
from app.models import BillingEvent, Plan, PlanFeature, PlanPrice, Subscription, Tenant, TenantUser
from app.routers.account import get_current_user
from app.services.audit_service import write_audit_log
from app.services.entitlement_service import EntitlementService
from app.services.billing_enforcement_service import BillingEnforcementService
from app.services.tenant_service import get_current_tenant
from app.services.trial_service import TrialService
from app.services.usage_service import UsageService

router = APIRouter(prefix="/billing", tags=["billing"])
admin_router = APIRouter(prefix="/admin/billing", tags=["admin-billing"])

class CheckoutRequest(BaseModel):
    plan_code: str = Field(min_length=1, max_length=64)
    billing_interval: str = Field(pattern="^(monthly|annual)$")
    success_path: str | None = Field(default=None, max_length=300)
    cancel_path: str | None = Field(default=None, max_length=300)

def _provider_value(value, key: str):
    return value.get(key) if isinstance(value, dict) else getattr(value, key, None)

def _plan(plan: Plan, features: list[PlanFeature] | None = None) -> dict:
    return {"code": plan.code, "name": plan.name, "description": plan.description, "monthly_price_cents": plan.monthly_price_cents, "annual_price_cents": plan.annual_price_cents, "currency": plan.currency, "features": [{"feature_key": f.feature_key, "enabled": f.enabled, "limit_value": f.limit_value, "limit_unit": f.limit_unit} for f in features or []]}

@router.get("/plans")
def public_plans(db: Session = Depends(get_db), user: TenantUser = Depends(get_current_user)):
    plans = db.execute(select(Plan).where(Plan.is_active.is_(True), Plan.is_public.is_(True)).order_by(Plan.sort_order)).scalars().all()
    return [_plan(plan, db.execute(select(PlanFeature).where(PlanFeature.plan_id == plan.id)).scalars().all()) for plan in plans]

@router.get("/usage")
def usage_billing(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(get_current_user)):
    """Read-only, tenant-scoped observational usage. It never enforces limits."""
    return UsageService(db).usage_view(tenant.id, EntitlementService(db).get_effective_entitlements(tenant.id))

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
    enforcement = BillingEnforcementService(db)
    access_mode, grace_ends_at = enforcement.workspace_access_mode(tenant.id)
    return {"tenant_id": str(tenant.id), "plan": _plan(plan, db.execute(select(PlanFeature).where(PlanFeature.plan_id == plan.id)).scalars().all()) if plan else None, "subscription": None if not subscription else {"status": subscription.status, "provider": subscription.provider, "billing_interval": subscription.billing_interval, "trial_started_at": subscription.trial_started_at, "trial_ends_at": subscription.trial_ends_at, "current_period_end": subscription.current_period_end, "cancel_at_period_end": subscription.cancel_at_period_end}, "trial": is_trial, "days_remaining": trial_service.days_remaining(tenant.id), "expired": bool(subscription and subscription.status == "expired"), "effective_entitlements": list(service.get_effective_entitlements(tenant.id).values()), "enforcement_enabled": settings.billing_enforcement_enabled, "enforcement_mode": enforcement.mode.value, "workspace_access_mode": access_mode.value, "grace_period_ends_at": grace_ends_at, "billing_ui_enabled": settings.billing_ui_enabled, "stripe_enabled": settings.stripe_enabled, "usage_snapshot": UsageService(db).current_snapshot(tenant.id), "current_period": UsageService(db).usage_view(tenant.id, service.get_effective_entitlements(tenant.id))["current_period"], "top_metrics": UsageService(db).usage_view(tenant.id, service.get_effective_entitlements(tenant.id))["metrics"][:5]}

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

def _billing_manager(user: TenantUser = Depends(get_current_user)) -> TenantUser:
    return _admin(user)

@router.post("/checkout")
def checkout(payload: CheckoutRequest, request: Request, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(_billing_manager)):
    if not settings.stripe_enabled:
        raise HTTPException(503, "Cobrança online temporariamente indisponível.")
    plan = db.execute(select(Plan).where(Plan.code == payload.plan_code, Plan.is_active.is_(True), Plan.is_public.is_(True))).scalars().first()
    if not plan: raise HTTPException(422, "Plano indisponível")
    price = db.execute(select(PlanPrice).where(PlanPrice.plan_id == plan.id, PlanPrice.provider == "stripe", PlanPrice.billing_interval == payload.billing_interval, PlanPrice.is_active.is_(True))).scalars().first()
    if not price: raise HTTPException(409, "Preço Stripe não configurado para este plano")
    subscription = db.execute(select(Subscription).where(Subscription.tenant_id == tenant.id)).scalars().first()
    if not subscription: raise HTTPException(409, "Assinatura interna não encontrada")
    if subscription.provider == "stripe" and subscription.status in {"active", "trialing", "past_due"}:
        raise HTTPException(409, "Use o portal de cobrança para gerenciar a assinatura atual")
    provider = StripeBillingProvider()
    try:
        if not subscription.external_customer_id:
            customer = provider.create_customer(tenant_id=str(tenant.id), email=user.email)
            subscription.external_customer_id = str(_provider_value(customer, "id"))
            write_audit_log(db, action="STRIPE_CUSTOMER_CREATED", tenant_id=tenant.id, user_id=user.id, entity_type="subscription", entity_id=subscription.id, request=request)
        root = settings.stripe_success_url.rstrip("/")
        success_url = f"{root}{payload.success_path}" if root and payload.success_path and payload.success_path.startswith("/") else settings.stripe_success_url
        cancel_url = f"{settings.stripe_cancel_url.rstrip('/')}{payload.cancel_path}" if settings.stripe_cancel_url and payload.cancel_path and payload.cancel_path.startswith("/") else settings.stripe_cancel_url
        session = provider.create_checkout_session(customer=subscription.external_customer_id, mode="subscription", line_items=[{"price": price.external_price_id, "quantity": 1}], success_url=success_url, cancel_url=cancel_url, metadata={"tenant_id": str(tenant.id), "internal_subscription_id": str(subscription.id), "plan_code": plan.code})
    except Exception as exc:
        raise HTTPException(503, "Não foi possível iniciar a cobrança online") from exc
    write_audit_log(db, action="CHECKOUT_SESSION_CREATED", tenant_id=tenant.id, user_id=user.id, entity_type="subscription", entity_id=subscription.id, request=request)
    db.commit()
    return {"checkout_url": _provider_value(session, "url")}

@router.post("/portal")
def portal(request: Request, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(_billing_manager)):
    if not settings.stripe_enabled: raise HTTPException(503, "Cobrança online temporariamente indisponível.")
    subscription = db.execute(select(Subscription).where(Subscription.tenant_id == tenant.id)).scalars().first()
    if not subscription or not subscription.external_customer_id: raise HTTPException(409, "Nenhum cliente Stripe associado ao workspace")
    try: session = StripeBillingProvider().create_portal_session(customer=subscription.external_customer_id, return_url=settings.stripe_portal_return_url)
    except Exception as exc: raise HTTPException(503, "Não foi possível abrir o portal de cobrança") from exc
    write_audit_log(db, action="CUSTOMER_PORTAL_OPENED", tenant_id=tenant.id, user_id=user.id, entity_type="subscription", entity_id=subscription.id, request=request); db.commit()
    return {"portal_url": _provider_value(session, "url")}

@router.post("/webhooks/stripe")
async def stripe_webhook(request: Request, db: Session = Depends(get_db)):
    raw = await request.body(); signature = request.headers.get("stripe-signature", "")
    try: event = StripeBillingProvider().validate_webhook(raw, signature)
    except Exception as exc: raise HTTPException(400, "Assinatura Stripe inválida") from exc
    event_id, event_type = str(event.get("id")), str(event.get("type"))
    existing = db.execute(select(BillingEvent).where(BillingEvent.provider == "stripe", BillingEvent.external_event_id == event_id)).scalars().first()
    if existing: return {"received": True, "duplicate": True}
    ledger = BillingEvent(provider="stripe", external_event_id=event_id, event_type=event_type, payload_hash=hashlib.sha256(raw).hexdigest(), status="processing", attempts=1, metadata_json={"livemode": bool(event.get("livemode", False))})
    db.add(ledger); db.flush()
    try:
        row = StripeWebhookService(db).process(event); ledger.status, ledger.processed_at = "processed", datetime.utcnow()
        if row: write_audit_log(db, action="BILLING_WEBHOOK_PROCESSED", tenant_id=row.tenant_id, entity_type="billing_event", entity_id=ledger.id)
        db.commit()
    except Exception as exc:
        ledger.status, ledger.error_code, ledger.error_message = "failed", "processing_error", str(exc)[:300]; db.commit()
        raise HTTPException(500, "Falha temporária ao processar webhook") from exc
    return {"received": True}

@admin_router.get("/plans")
def admin_plans(db: Session = Depends(get_db), user: TenantUser = Depends(_admin)):
    return [_plan(plan, db.execute(select(PlanFeature).where(PlanFeature.plan_id == plan.id)).scalars().all()) for plan in db.execute(select(Plan).order_by(Plan.sort_order)).scalars().all()]

@admin_router.get("/tenants/{tenant_id}")
def admin_tenant_billing(tenant_id: str = Path(...), db: Session = Depends(get_db), user: TenantUser = Depends(_admin)):
    tenant = db.get(Tenant, tenant_id)
    if not tenant: raise HTTPException(status_code=404, detail="Tenant não encontrado")
    subscription = db.execute(select(Subscription).where(Subscription.tenant_id == tenant.id)).scalars().first()
    enforcement = BillingEnforcementService(db)
    access_mode, grace_ends_at = enforcement.workspace_access_mode(tenant.id)
    return {"tenant_id": str(tenant.id), "subscription_status": subscription.status if subscription else "legacy", "enforcement_mode": enforcement.mode.value, "workspace_access_mode": access_mode.value, "grace_period_ends_at": grace_ends_at, "effective_entitlements": list(EntitlementService(db).get_effective_entitlements(tenant.id).values())}


@admin_router.get("/tenants/{tenant_id}/usage")
def admin_tenant_usage(tenant_id: str = Path(...), db: Session = Depends(get_db), user: TenantUser = Depends(_admin)):
    tenant = db.get(Tenant, tenant_id)
    if not tenant: raise HTTPException(status_code=404, detail="Tenant não encontrado")
    return UsageService(db).usage_view(tenant.id, EntitlementService(db).get_effective_entitlements(tenant.id))
