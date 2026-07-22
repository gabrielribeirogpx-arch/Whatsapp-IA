from __future__ import annotations
from datetime import datetime, timezone
from typing import Any
from uuid import UUID
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.billing.stripe_provider import StripeBillingProvider
from app.models import PlanPrice, Subscription, TenantEntitlement
from app.services.audit_service import write_audit_log

def _get(value: Any, key: str, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)
def _date(value):
    return datetime.fromtimestamp(value, timezone.utc).replace(tzinfo=None) if value else None

class StripeWebhookService:
    """Applies only verified Stripe events; redirects are deliberately ignored."""
    def __init__(self, db: Session): self.db, self.provider = db, StripeBillingProvider()
    def process(self, event: Any) -> Subscription | None:
        event_type, data = _get(event, "type"), _get(_get(event, "data", {}), "object", {})
        if event_type == "checkout.session.completed":
            return self._checkout_completed(data)
        if event_type.startswith("customer.subscription."):
            return self._subscription(data, event_type)
        if event_type in {"invoice.paid", "invoice.payment_succeeded", "invoice.payment_failed"}:
            return self._invoice(data, event_type)
        return None
    def _by_ids(self, data: Any) -> Subscription | None:
        metadata = _get(data, "metadata", {}) or {}
        tenant_id = metadata.get("tenant_id") if isinstance(metadata, dict) else None
        if tenant_id:
            try:
                row = self.db.execute(select(Subscription).where(Subscription.tenant_id == UUID(str(tenant_id)))).scalars().first()
                if row: return row
            except ValueError: pass
        subscription_id = _get(data, "subscription") or _get(data, "id")
        if subscription_id:
            return self.db.execute(select(Subscription).where(Subscription.external_subscription_id == str(subscription_id))).scalars().first()
        customer = _get(data, "customer")
        return self.db.execute(select(Subscription).where(Subscription.external_customer_id == str(customer))).scalars().first() if customer else None
    def _checkout_completed(self, session: Any) -> Subscription | None:
        row = self._by_ids(session)
        if row:
            row.external_customer_id = str(_get(session, "customer") or row.external_customer_id)
            row.external_subscription_id = str(_get(session, "subscription") or row.external_subscription_id)
            write_audit_log(self.db, action="CHECKOUT_SESSION_COMPLETED", tenant_id=row.tenant_id, entity_type="subscription", entity_id=row.id)
        return row
    def _subscription(self, item: Any, event_type: str) -> Subscription | None:
        row = self._by_ids(item)
        if not row: return None
        price = _get((_get(item, "items", {}) or {}).get("data", [{}])[0], "price", {}) if isinstance(_get(item, "items", {}), dict) else {}
        price_id = _get(price, "id")
        mapped = self.db.execute(select(PlanPrice).where(PlanPrice.provider == "stripe", PlanPrice.external_price_id == price_id, PlanPrice.is_active.is_(True))).scalars().first()
        if not mapped: return row  # Never activate an unconfigured Stripe price.
        row.plan_id, row.provider, row.external_customer_id = mapped.plan_id, "stripe", str(_get(item, "customer") or row.external_customer_id)
        row.external_subscription_id, row.external_price_id = str(_get(item, "id")), price_id
        row.billing_interval, row.status = mapped.billing_interval, self.provider.map_status(_get(item, "status"))
        row.current_period_start, row.current_period_end = _date(_get(item, "current_period_start")), _date(_get(item, "current_period_end"))
        row.cancel_at_period_end, row.canceled_at = bool(_get(item, "cancel_at_period_end", False)), _date(_get(item, "canceled_at"))
        if row.status in {"active", "trialing"}: row.trial_ends_at = _date(_get(item, "trial_end"))
        action = "SUBSCRIPTION_CANCELED" if event_type.endswith("deleted") else ("SUBSCRIPTION_ACTIVATED" if event_type.endswith("created") else "SUBSCRIPTION_UPDATED")
        write_audit_log(self.db, action=action, tenant_id=row.tenant_id, entity_type="subscription", entity_id=row.id, metadata={"status": row.status, "source": "stripe_webhook"})
        return row
    def _invoice(self, invoice: Any, event_type: str) -> Subscription | None:
        row = self._by_ids(invoice)
        if row:
            if event_type == "invoice.payment_failed": row.status = "past_due"; action = "PAYMENT_FAILED"
            else: action = "PAYMENT_SUCCEEDED"
            write_audit_log(self.db, action=action, tenant_id=row.tenant_id, entity_type="subscription", entity_id=row.id)
        return row
