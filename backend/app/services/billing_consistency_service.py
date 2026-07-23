"""Read-only billing integrity checks safe to run before Stripe is configured."""
from __future__ import annotations

from collections import Counter
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.features import ALL_FEATURE_KEYS
from app.core.config import settings
from app.models import Plan, PlanFeature, Subscription, Tenant, TenantEntitlement, UsageEvent


class BillingConsistencyService:
    """Report data inconsistencies without mutating subscriptions or usage."""

    def __init__(self, db: Session):
        self.db = db

    def check(self) -> dict:
        tenants = self.db.execute(select(Tenant)).scalars().all()
        plans = self.db.execute(select(Plan)).scalars().all()
        subscriptions = self.db.execute(select(Subscription)).scalars().all()
        plan_ids = {plan.id for plan in plans}
        tenant_ids = {tenant.id for tenant in tenants}
        features_by_plan = Counter(feature.plan_id for feature in self.db.execute(select(PlanFeature)).scalars())
        findings: list[dict] = []

        subscribed_tenant_ids = {subscription.tenant_id for subscription in subscriptions}
        for tenant in tenants:
            if tenant.id not in subscribed_tenant_ids:
                findings.append({"check": "tenant_without_subscription", "tenant_id": str(tenant.id), "severity": "warning"})
        for subscription in subscriptions:
            if subscription.plan_id not in plan_ids:
                findings.append({"check": "subscription_without_plan", "subscription_id": str(subscription.id), "severity": "error"})
            if subscription.status == "trialing" and subscription.trial_ends_at is None:
                findings.append({"check": "trial_without_end", "subscription_id": str(subscription.id), "severity": "error"})
            if subscription.status == "legacy":
                disabled = [feature.feature_key for feature in self.db.execute(select(PlanFeature).where(PlanFeature.plan_id == subscription.plan_id, PlanFeature.enabled.is_(False))).scalars()]
                if disabled:
                    findings.append({"check": "legacy_without_full_access", "subscription_id": str(subscription.id), "severity": "error", "features": disabled})
        for plan in plans:
            if not features_by_plan[plan.id]:
                findings.append({"check": "plan_without_entitlements", "plan_id": str(plan.id), "severity": "warning"})
        for tenant_id, count in Counter(subscription.tenant_id for subscription in subscriptions).items():
            if count > 1:
                findings.append({"check": "multiple_effective_subscriptions", "tenant_id": str(tenant_id), "severity": "error", "count": count})
        for event in self.db.execute(select(UsageEvent)).scalars():
            if event.tenant_id not in tenant_ids:
                findings.append({"check": "orphan_usage", "usage_event_id": str(event.id), "severity": "warning"})
        for entitlement in self.db.execute(select(TenantEntitlement)).scalars():
            if entitlement.feature_key not in ALL_FEATURE_KEYS:
                findings.append({"check": "invalid_entitlement", "entitlement_id": str(entitlement.id), "severity": "error", "feature_key": entitlement.feature_key})

        stripe = {"status": "ok" if settings.stripe_configured else "skipped_not_configured"}
        return {"checked_at": datetime.utcnow().isoformat(), "healthy": not any(item["severity"] == "error" for item in findings), "findings": findings, "stripe": stripe}
