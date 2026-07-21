"""Internal, non-enforcing lifecycle for Wazza trials."""
from __future__ import annotations

from datetime import datetime, timedelta
from math import ceil
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.billing import Plan, PlanFeature, Subscription, SubscriptionStatus, TenantEntitlement
from app.services.audit_service import write_audit_log

TRIAL_PLAN_CODE = "growth_trial"
TRIAL_DURATION_DAYS = 14


class TrialService:
    def __init__(self, db: Session):
        self.db = db

    def _subscription(self, tenant_id: UUID) -> Subscription | None:
        return self.db.execute(select(Subscription).where(Subscription.tenant_id == tenant_id)).scalars().first()

    def _trial_plan(self) -> Plan:
        plan = self.db.execute(select(Plan).where(Plan.code == TRIAL_PLAN_CODE)).scalars().first()
        if plan is None:
            raise RuntimeError("Plano interno growth_trial não foi encontrado; execute as migrations")
        return plan

    def start_trial(self, tenant_id: UUID, *, now: datetime | None = None) -> Subscription:
        now = now or datetime.utcnow()
        subscription = self._subscription(tenant_id)
        if subscription is not None:
            return subscription
        subscription = Subscription(tenant_id=tenant_id, plan_id=self._trial_plan().id, status=SubscriptionStatus.TRIALING.value,
                                    trial_started_at=now, trial_ends_at=now + timedelta(days=TRIAL_DURATION_DAYS), metadata_json={"trial_days": TRIAL_DURATION_DAYS})
        self.db.add(subscription)
        self.db.flush()
        self.renew_entitlements(subscription)
        write_audit_log(self.db, action="TRIAL_STARTED", tenant_id=tenant_id, entity_type="subscription", entity_id=subscription.id,
                        metadata={"trial_ends_at": subscription.trial_ends_at, "days": TRIAL_DURATION_DAYS})
        return subscription

    def renew_entitlements(self, subscription: Subscription) -> None:
        """Mirror trial-plan capabilities as expiring trial entitlements for future enforcement."""
        features = self.db.execute(select(PlanFeature).where(PlanFeature.plan_id == subscription.plan_id)).scalars().all()
        existing = {row.feature_key: row for row in self.db.execute(select(TenantEntitlement).where(TenantEntitlement.tenant_id == subscription.tenant_id, TenantEntitlement.source == "trial")).scalars()}
        for feature in features:
            entitlement = existing.pop(feature.feature_key, None)
            if entitlement is None:
                entitlement = TenantEntitlement(tenant_id=subscription.tenant_id, feature_key=feature.feature_key, source="trial")
                self.db.add(entitlement)
            entitlement.enabled, entitlement.limit_value, entitlement.expires_at = feature.enabled, feature.limit_value, subscription.trial_ends_at
        for entitlement in existing.values():
            self.db.delete(entitlement)

    def is_trial(self, tenant_id: UUID) -> bool:
        subscription = self._subscription(tenant_id)
        return bool(subscription and subscription.status == SubscriptionStatus.TRIALING.value)

    def status(self, tenant_id: UUID) -> str:
        subscription = self._subscription(tenant_id)
        return subscription.status if subscription else SubscriptionStatus.LEGACY.value

    def days_remaining(self, tenant_id: UUID, *, now: datetime | None = None) -> int:
        subscription = self._subscription(tenant_id)
        if not subscription or subscription.status != SubscriptionStatus.TRIALING.value or not subscription.trial_ends_at:
            return 0
        seconds = (subscription.trial_ends_at - (now or datetime.utcnow())).total_seconds()
        return max(0, ceil(seconds / 86400))

    def extend_trial(self, tenant_id: UUID, days: int, *, now: datetime | None = None) -> Subscription:
        if days <= 0:
            raise ValueError("A extensão do trial deve ser de pelo menos um dia")
        subscription = self._subscription(tenant_id)
        if not subscription or subscription.status != SubscriptionStatus.TRIALING.value:
            raise ValueError("Tenant não possui trial ativo")
        subscription.trial_ends_at = max(subscription.trial_ends_at or now or datetime.utcnow(), now or datetime.utcnow()) + timedelta(days=days)
        self.renew_entitlements(subscription)
        write_audit_log(self.db, action="TRIAL_EXTENDED", tenant_id=tenant_id, entity_type="subscription", entity_id=subscription.id,
                        metadata={"days": days, "trial_ends_at": subscription.trial_ends_at})
        return subscription

    def finish_trial(self, tenant_id: UUID) -> Subscription | None:
        subscription = self._subscription(tenant_id)
        if subscription and subscription.status == SubscriptionStatus.TRIALING.value:
            subscription.trial_ends_at = datetime.utcnow()
        return self.expire_trial(tenant_id)

    def expire_trial(self, tenant_id: UUID, *, now: datetime | None = None) -> Subscription | None:
        subscription = self._subscription(tenant_id)
        if not subscription or subscription.status != SubscriptionStatus.TRIALING.value or not subscription.trial_ends_at:
            return subscription
        if subscription.trial_ends_at > (now or datetime.utcnow()):
            return subscription
        subscription.status = SubscriptionStatus.EXPIRED.value
        write_audit_log(self.db, action="TRIAL_EXPIRED", tenant_id=tenant_id, entity_type="subscription", entity_id=subscription.id,
                        metadata={"trial_ends_at": subscription.trial_ends_at})
        return subscription

    def expire_due_trials(self, *, now: datetime | None = None) -> int:
        now = now or datetime.utcnow()
        due = self.db.execute(select(Subscription).where(Subscription.status == SubscriptionStatus.TRIALING.value, Subscription.trial_ends_at <= now)).scalars().all()
        for subscription in due:
            self.expire_trial(subscription.tenant_id, now=now)
        return len(due)
