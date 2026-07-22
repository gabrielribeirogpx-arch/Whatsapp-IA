"""Reusable FastAPI billing guards with collision-safe dependency arguments."""
from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

from fastapi import Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.billing_enforcement_service import BillingEnforcementService, EnforcementDecision
from app.services.tenant_service import get_current_tenant


def require_billing_feature(feature_key: str):
    def guard(
        db: Session = Depends(get_db),
        workspace=Depends(get_current_tenant),
    ) -> EnforcementDecision:
        return BillingEnforcementService(db).require_feature(workspace.id, feature_key)
    return guard


def require_billing_capacity(feature_key: str, current_resolver: Callable[[Session, UUID], int]):
    def guard(
        db: Session = Depends(get_db),
        workspace=Depends(get_current_tenant),
    ) -> EnforcementDecision:
        return BillingEnforcementService(db).require_capacity(workspace.id, feature_key, current_resolver(db, workspace.id))
    return guard


def require_workspace_access(operation: str = "write"):
    def guard(
        db: Session = Depends(get_db),
        workspace=Depends(get_current_tenant),
    ) -> EnforcementDecision:
        decision = BillingEnforcementService(db).evaluate_subscription_access(workspace.id, operation=operation)
        return BillingEnforcementService(db)._require(decision)
    return guard
