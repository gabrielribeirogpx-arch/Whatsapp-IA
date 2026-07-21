from __future__ import annotations

import logging
from datetime import datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.billing.features import ALL_FEATURE_KEYS
from app.core.config import settings
from app.models.billing import PlanFeature, Subscription, TenantEntitlement

logger = logging.getLogger(__name__)
PRECEDENCE = {"manual": 0, "enterprise_contract": 1, "addon": 2, "promotion": 3, "trial": 4, "plan": 5, "legacy": 6}


class EntitlementService:
    """Read-only Phase 1 resolver. Limits are overrides (not additive); NULL means unlimited."""
    def __init__(self, db: Session): self.db = db

    def get_effective_entitlements(self, tenant_id: UUID) -> dict[str, dict]:
        subscription = self.db.execute(select(Subscription).where(Subscription.tenant_id == tenant_id)).scalars().first()
        result: dict[str, dict] = {}
        if subscription:
            for item in self.db.execute(select(PlanFeature).where(PlanFeature.plan_id == subscription.plan_id)).scalars():
                result[item.feature_key] = {"feature_key": item.feature_key, "enabled": item.enabled, "limit_value": item.limit_value, "limit_unit": item.limit_unit, "source": "plan"}
        now = datetime.utcnow()
        rows = self.db.execute(select(TenantEntitlement).where(TenantEntitlement.tenant_id == tenant_id)).scalars()
        for item in sorted((row for row in rows if row.expires_at is None or row.expires_at > now), key=lambda row: PRECEDENCE.get(row.source, 99), reverse=True):
            existing = result.get(item.feature_key)
            # Lower numeric precedence wins; plan data is deliberately the base layer.
            if existing is None or PRECEDENCE.get(item.source, 99) < PRECEDENCE.get(existing["source"], 99):
                result[item.feature_key] = {"feature_key": item.feature_key, "enabled": item.enabled, "limit_value": item.limit_value, "limit_unit": None, "source": item.source}
        if not subscription:  # compatibility for tenants created before the migration or during rollout
            result = {key: {"feature_key": key, "enabled": True, "limit_value": None, "limit_unit": None, "source": "legacy"} for key in ALL_FEATURE_KEYS}
        return result

    def has_feature(self, tenant_id: UUID, feature_key: str) -> bool:
        return self.get_effective_entitlements(tenant_id).get(feature_key, {}).get("enabled", not settings.billing_enforcement_enabled)

    def get_limit(self, tenant_id: UUID, feature_key: str) -> int | None:
        return self.get_effective_entitlements(tenant_id).get(feature_key, {}).get("limit_value")

    def require_feature(self, tenant_id: UUID, feature_key: str) -> None:
        if not settings.billing_enforcement_enabled: return
        if not self.has_feature(tenant_id, feature_key): raise HTTPException(status_code=403, detail="Recurso indisponível no plano atual")

    def require_capacity(self, tenant_id: UUID, feature_key: str, current: int, increment: int = 1) -> None:
        if not settings.billing_enforcement_enabled: return
        limit = self.get_limit(tenant_id, feature_key)
        if limit is not None and current + increment > limit: raise HTTPException(status_code=403, detail="Limite do plano atingido")

    def explain_feature(self, tenant_id: UUID, feature_key: str) -> dict:
        return self.get_effective_entitlements(tenant_id).get(feature_key, {"feature_key": feature_key, "enabled": not settings.billing_enforcement_enabled, "limit_value": None, "source": "legacy"})
