# Product Analytics — privacy

Product Analytics is an internal, tenant-scoped product-use dataset and is independent from technical observability, audit logs, billing usage, and Stripe. All timestamps and daily aggregation use UTC.

## Safety

The master flag `PRODUCT_ANALYTICS_ENABLED=false` disables capture and administrative read APIs without changing product behavior. Capture is best-effort: failures are logged without sensitive properties and are never propagated into product operations. Raw retention is configured with `PRODUCT_ANALYTICS_RAW_RETENTION_DAYS` (default 180); a deletion job must support dry-run and audit logging before production use.

## Operations

Use `python -m app.analytics.aggregate_product_metrics --date YYYY-MM-DD --dry-run` to preview UTC aggregation and `python -m app.analytics.backfill_activation_state --dry-run` to inspect conservative state backfill. Rebuild is refused in production by default.
