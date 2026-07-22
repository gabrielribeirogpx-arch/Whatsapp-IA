"""Tenant-scoped, progressive billing policy evaluation.

This module is intentionally the only place that turns a plan into an access
decision.  Routers/services may ask it to *require* an operation, but must not
duplicate status or plan conditionals.  It never mutates or removes resources.
"""
from __future__ import annotations

import enum
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.billing import Plan, PlanFeature, Subscription, SubscriptionStatus
from app.services.usage_service import UsageService
from app.services.audit_service import write_audit_log
from app.services.entitlement_service import EntitlementService

logger = logging.getLogger(__name__)
GRACE_PERIOD_DAYS = 3
BILLING_URL = "/dashboard/settings?section=billing"


class EnforcementMode(str, enum.Enum):
    DISABLED = "disabled"
    OBSERVE = "observe"
    WARN = "warn"
    SOFT = "soft"
    HARD = "hard"


class WorkspaceAccessMode(str, enum.Enum):
    FULL = "full"
    WARNING = "warning"
    GRACE = "grace"
    RESTRICTED_READ_ONLY = "restricted_read_only"
    SUSPENDED_AUTOMATION = "suspended_automation"


@dataclass
class EnforcementDecision:
    allowed: bool
    enforcement_mode: str
    reason_code: str
    feature_key: str | None = None
    current_value: int | float | None = None
    limit_value: int | None = None
    requested_increment: int = 0
    projected_value: int | float | None = None
    subscription_status: str = SubscriptionStatus.LEGACY.value
    trial_status: str | None = None
    grace_period_ends_at: datetime | None = None
    upgrade_required: bool = False
    recommended_plan_code: str | None = None
    message: str = "Operação permitida."
    metadata: dict[str, Any] = field(default_factory=dict)

    def error_payload(self) -> dict[str, Any]:
        code = "BILLING_FEATURE_NOT_INCLUDED" if self.reason_code == "FEATURE_NOT_INCLUDED" else "BILLING_LIMIT_REACHED"
        return {"error": {"code": code, "reason_code": self.reason_code, "feature_key": self.feature_key,
                           "message": self.message, "current_value": self.current_value,
                           "limit_value": self.limit_value, "projected_value": self.projected_value,
                           "upgrade_required": self.upgrade_required,
                           "recommended_plan_code": self.recommended_plan_code,
                           "billing_url": BILLING_URL}}

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PlanCompatibilityReport:
    compatible: bool
    violations: list[dict[str, Any]]
    current: dict[str, int | float]
    target_limit: dict[str, int | None]
    affected_resource_ids: dict[str, list[str]] = field(default_factory=dict)  # internal only
    required_actions: list[str] = field(default_factory=list)
    grace_period: datetime | None = None


class BillingEnforcementService:
    """Evaluate billing policy with fail-open behaviour outside reliable hard mode."""
    def __init__(self, db: Session, *, now: datetime | None = None):
        self.db, self.now = db, now or datetime.utcnow()
        self.entitlements = EntitlementService(db)

    @property
    def mode(self) -> EnforcementMode:
        if not settings.billing_enforcement_enabled:
            return EnforcementMode.DISABLED
        try:
            return EnforcementMode(settings.billing_enforcement_mode)
        except ValueError:
            logger.error("Invalid BILLING_ENFORCEMENT_MODE=%s", settings.billing_enforcement_mode)
            return EnforcementMode.OBSERVE

    def _subscription(self, tenant_id: UUID) -> Subscription | None:
        return self.db.execute(select(Subscription).where(Subscription.tenant_id == tenant_id)).scalars().first()

    def _base(self, tenant_id: UUID, feature_key: str | None = None) -> tuple[Subscription | None, EnforcementDecision]:
        sub = self._subscription(tenant_id)
        status = sub.status if sub else SubscriptionStatus.LEGACY.value
        return sub, EnforcementDecision(True, self.mode.value, "ALLOWED", feature_key=feature_key, subscription_status=status)

    def workspace_access_mode(self, tenant_id: UUID) -> tuple[WorkspaceAccessMode, datetime | None]:
        sub = self._subscription(tenant_id)
        if not sub or sub.status == SubscriptionStatus.LEGACY.value:
            return WorkspaceAccessMode.FULL, None
        grace_end = sub.grace_period_ends_at
        if sub.status in {SubscriptionStatus.TRIALING.value, SubscriptionStatus.EXPIRED.value} and sub.trial_ends_at and sub.trial_ends_at <= self.now:
            grace_end = grace_end or sub.trial_ends_at + timedelta(days=GRACE_PERIOD_DAYS)
        if sub.status in {SubscriptionStatus.PAST_DUE.value, SubscriptionStatus.GRACE_PERIOD.value}:
            grace_end = grace_end or self.now + timedelta(days=GRACE_PERIOD_DAYS)
        if grace_end and grace_end > self.now:
            return WorkspaceAccessMode.GRACE, grace_end
        if sub.status in {SubscriptionStatus.EXPIRED.value, SubscriptionStatus.PAUSED.value}:
            return WorkspaceAccessMode.RESTRICTED_READ_ONLY, grace_end
        if sub.status == SubscriptionStatus.CANCELED.value and (not sub.current_period_end or sub.current_period_end <= self.now):
            return WorkspaceAccessMode.RESTRICTED_READ_ONLY, grace_end
        return (WorkspaceAccessMode.WARNING if sub.cancel_at_period_end else WorkspaceAccessMode.FULL), grace_end

    def _apply_mode(self, decision: EnforcementDecision, *, blockable: bool) -> EnforcementDecision:
        would_block = not decision.allowed
        if not would_block:
            return decision
        decision.metadata["would_block"] = True
        if self.mode in {EnforcementMode.DISABLED, EnforcementMode.OBSERVE, EnforcementMode.WARN} or not blockable or not self._domain_enabled(decision.feature_key):
            decision.allowed = True
            if self.mode == EnforcementMode.DISABLED:
                decision.reason_code = "ENFORCEMENT_DISABLED"
            if self.mode == EnforcementMode.WARN:
                decision.metadata["warning"] = True
            if not self._domain_enabled(decision.feature_key):
                decision.metadata["domain_enforcement_disabled"] = True
            return decision
        return decision

    @staticmethod
    def _domain_enabled(feature_key: str | None) -> bool:
        """Group flags keep rollout scoped even after the master switch is on."""
        if feature_key in {"users", "active_users"}:
            return settings.billing_enforce_users
        if feature_key == "whatsapp_numbers":
            return settings.billing_enforce_whatsapp
        if feature_key == "published_flows":
            return settings.billing_enforce_flows
        if feature_key and feature_key.startswith("ai_"):
            return settings.billing_enforce_ai
        if feature_key in {"mcp", "api_access"}:
            return settings.billing_enforce_mcp
        if feature_key and feature_key.startswith("observability_"):
            return settings.billing_enforce_observability
        # Other non-rollout features use the master policy.
        return True

    def evaluate_subscription_access(self, tenant_id: UUID, *, operation: str = "write") -> EnforcementDecision:
        sub, decision = self._base(tenant_id)
        if not sub or sub.status == SubscriptionStatus.LEGACY.value:
            decision.reason_code, decision.message = "LEGACY_UNLIMITED", "Workspace Legacy sem limites comerciais."
            return decision
        access, grace = self.workspace_access_mode(tenant_id)
        decision.grace_period_ends_at = grace
        if operation in {"read", "billing", "export"}: return decision
        if access == WorkspaceAccessMode.GRACE:
            decision.reason_code, decision.message = "GRACE_PERIOD_ACTIVE", "Período de carência ativo; recursos existentes permanecem disponíveis."
            return decision
        if access == WorkspaceAccessMode.RESTRICTED_READ_ONLY:
            decision.allowed, decision.reason_code, decision.message = False, "SUBSCRIPTION_EXPIRED", "Workspace restrito até a regularização da assinatura."
            decision.upgrade_required = True
            return self._apply_mode(decision, blockable=True)
        return decision

    def evaluate_feature(self, tenant_id: UUID, feature_key: str, context: dict | None = None) -> EnforcementDecision:
        sub, decision = self._base(tenant_id, feature_key)
        if not sub or sub.status == SubscriptionStatus.LEGACY.value:
            decision.reason_code, decision.message = "LEGACY_UNLIMITED", "Workspace Legacy mantém todos os recursos."
            return decision
        try:
            item = self.entitlements.explain_feature(tenant_id, feature_key)
            if not item.get("enabled", False):
                decision.allowed, decision.reason_code = False, "FEATURE_NOT_INCLUDED"
                decision.message, decision.upgrade_required = "Este recurso não está incluído no plano atual.", True
                decision.recommended_plan_code = (context or {}).get("recommended_plan_code")
            return self._apply_mode(decision, blockable=True)
        except Exception:
            logger.exception("billing entitlement resolution failed tenant_id=%s", tenant_id)
            decision.reason_code, decision.message = "BILLING_CONFIGURATION_ERROR", "Não foi possível validar o plano agora."
            # Even hard mode only closes on explicitly trustworthy data.
            decision.allowed = self.mode != EnforcementMode.HARD
            return decision

    def evaluate_operation(self, tenant_id: UUID, feature_key: str | None = None, *, operation: str = "write", context: dict | None = None) -> EnforcementDecision:
        """Combine workspace and optional feature policy for creation/configuration operations."""
        access = self.evaluate_subscription_access(tenant_id, operation=operation)
        if not access.allowed or feature_key is None:
            return access
        feature = self.evaluate_feature(tenant_id, feature_key, context)
        if not feature.allowed:
            return feature
        if access.reason_code != "ALLOWED":
            feature.reason_code = access.reason_code
            feature.message = access.message
            feature.grace_period_ends_at = access.grace_period_ends_at
        return feature

    def evaluate_capacity(self, tenant_id: UUID, feature_key: str, current: int | float, increment: int = 1, context: dict | None = None) -> EnforcementDecision:
        sub, decision = self._base(tenant_id, feature_key)
        decision.current_value, decision.requested_increment, decision.projected_value = current, increment, current + increment
        if not sub or sub.status == SubscriptionStatus.LEGACY.value:
            decision.reason_code, decision.message = "LEGACY_UNLIMITED", "Workspace Legacy não possui limite de capacidade."
            return decision
        access = self.evaluate_subscription_access(tenant_id, operation="write")
        if not access.allowed:
            access.feature_key, access.current_value, access.requested_increment, access.projected_value = feature_key, current, increment, current + increment
            return access
        try:
            limit = self.entitlements.get_limit(tenant_id, feature_key)
            decision.limit_value = limit
            if limit is not None and increment > 0 and current + increment > limit:
                decision.allowed = False
                decision.reason_code = "LIMIT_REACHED" if current >= limit else "LIMIT_EXCEEDED"
                decision.message = f"Seu plano permite até {limit} {feature_key}."
                decision.upgrade_required = True
                decision.recommended_plan_code = (context or {}).get("recommended_plan_code")
            return self._apply_mode(decision, blockable=increment > 0)
        except Exception:
            logger.exception("billing usage resolution failed tenant_id=%s", tenant_id)
            decision.reason_code, decision.message = "USAGE_UNAVAILABLE", "Não foi possível validar o uso agora."
            decision.allowed = self.mode != EnforcementMode.HARD
            return decision

    def require_feature(self, tenant_id: UUID, feature_key: str, context: dict | None = None) -> EnforcementDecision:
        return self._require(self.evaluate_feature(tenant_id, feature_key, context))

    def require_capacity(self, tenant_id: UUID, feature_key: str, current: int | float, increment: int = 1, context: dict | None = None) -> EnforcementDecision:
        return self._require(self.evaluate_capacity(tenant_id, feature_key, current, increment, context))

    def compatibility_report(self, tenant_id: UUID, target_plan_code: str) -> PlanCompatibilityReport:
        """Report a downgrade incompatibility without changing any resource."""
        plan = self.db.execute(select(Plan).where(Plan.code == target_plan_code)).scalars().first()
        if plan is None:
            raise ValueError("Plano de destino não encontrado")
        limits = {f.feature_key: f.limit_value for f in self.db.execute(select(PlanFeature).where(PlanFeature.plan_id == plan.id)).scalars()}
        current = UsageService(self.db).current_snapshot(tenant_id)
        violations = []
        for key, used in current.items():
            limit = limits.get(key)
            if limit is not None and used > limit:
                violations.append({"feature_key": key, "current_value": used, "target_limit": limit,
                                   "message": f"Você possui {used:g} {key} e o novo plano permite {limit}. Recursos existentes permanecerão ativos; reduza o uso antes de expandir."})
        _, grace = self.workspace_access_mode(tenant_id)
        if violations:
            write_audit_log(self.db, action="DOWNGRADE_INCOMPATIBILITY_DETECTED", tenant_id=tenant_id,
                            entity_type="plan", entity_id=plan.id, metadata={"target_plan_code": target_plan_code, "violations": violations})
        return PlanCompatibilityReport(not violations, violations, current, limits, required_actions=["Reduza apenas os recursos que excedem o novo limite."] if violations else [], grace_period=grace)

    def _require(self, decision: EnforcementDecision) -> EnforcementDecision:
        if not decision.allowed:
            action = "BILLING_FEATURE_BLOCKED" if decision.reason_code == "FEATURE_NOT_INCLUDED" else "BILLING_LIMIT_BLOCKED"
            write_audit_log(self.db, action=action, entity_type="billing_enforcement", metadata=decision.as_dict())
            status = 403 if decision.reason_code == "FEATURE_NOT_INCLUDED" else 409
            raise HTTPException(status_code=status, detail=decision.error_payload())
        return decision
