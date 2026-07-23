# Billing Phase 6A — pre-launch without Stripe

This phase deliberately runs billing without an online payment provider. Set:

```env
BILLING_ENFORCEMENT_ENABLED=true
BILLING_ENFORCEMENT_MODE=observe
BILLING_UI_ENABLED=true
STRIPE_ENABLED=false
```

All `BILLING_ENFORCE_*` domain flags remain `false`. Do **not** set
`STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PUBLISHABLE_KEY`, URLs,
Products, Prices, or webhooks in this phase.

`GET /api/admin/billing/health` reports Stripe as `not_configured` without
making health fail. `GET /api/admin/billing/consistency` performs read-only
integrity checks; Stripe-specific checks are `skipped_not_configured` until
online billing is intentionally configured. `GET /api/admin/billing/operations`
is an owner/admin-only operational overview.
