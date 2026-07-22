# Stripe Billing Test Mode

Keep `STRIPE_ENABLED=false` until the database migration, Stripe products/prices, and webhook are verified. Set `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET`, `STRIPE_PUBLISHABLE_KEY`, `STRIPE_SUCCESS_URL`, `STRIPE_CANCEL_URL`, and `STRIPE_PORTAL_RETURN_URL` only in the deployment secret store; never commit them.

Create monthly and annual recurring Prices for each public Wazza plan, then persist their IDs in `plan_prices` with provider `stripe`. Forward local events with:

```bash
stripe listen --forward-to localhost:8000/api/billing/webhooks/stripe
```

Use Stripe Test Mode and a Stripe test card (for example `4242 4242 4242 4242`) to complete Checkout. Confirm that the `customer.subscription.*` webhook, rather than the success redirect, changes the internal plan. Retry an event in the Stripe dashboard to verify idempotency, test a failed invoice, open Customer Portal, and run reconciliation before enabling staging. `BILLING_ENFORCEMENT_ENABLED` must remain `false` throughout this phase.
