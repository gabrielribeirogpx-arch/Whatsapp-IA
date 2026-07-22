"""Lazy Stripe adapter: importing billing never requires a configured Stripe SDK."""
from __future__ import annotations
from typing import Any
from app.core.config import settings

class StripeBillingProvider:
    STATUS_MAP = {"trialing": "trialing", "active": "active", "past_due": "past_due", "unpaid": "past_due", "canceled": "canceled", "incomplete": "incomplete", "incomplete_expired": "expired", "paused": "paused"}
    def _client(self):
        if not settings.stripe_enabled or not settings.stripe_secret_key:
            raise RuntimeError("Stripe billing is unavailable")
        import stripe
        return stripe.StripeClient(settings.stripe_secret_key)
    def create_customer(self, *, tenant_id: str, email: str | None = None) -> Any:
        return self._client().v1.customers.create(params={"email": email, "metadata": {"tenant_id": tenant_id}})
    def create_checkout_session(self, **params: Any) -> Any:
        return self._client().v1.checkout.sessions.create(params=params)
    def create_portal_session(self, *, customer: str, return_url: str) -> Any:
        return self._client().v1.billing_portal.sessions.create(params={"customer": customer, "return_url": return_url})
    def retrieve_subscription(self, subscription_id: str) -> Any:
        return self._client().v1.subscriptions.retrieve(subscription_id)
    def retrieve_price(self, price_id: str) -> Any:
        return self._client().v1.prices.retrieve(price_id)
    def validate_webhook(self, payload: bytes, signature: str) -> Any:
        if not settings.stripe_webhook_secret:
            raise ValueError("Stripe webhook is unavailable")
        import stripe
        return stripe.Webhook.construct_event(payload, signature, settings.stripe_webhook_secret)
    def map_status(self, status: str | None) -> str:
        return self.STATUS_MAP.get(status or "", "incomplete")
