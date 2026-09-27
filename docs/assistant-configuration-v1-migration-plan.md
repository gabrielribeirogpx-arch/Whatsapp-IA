# Migration plan — canonical assistant configuration V1

This plan was recorded before creating the migration, after reviewing the existing
`MarketplaceInstallation` JSON fields. `customization_state`, snapshots, and
resource metadata have separate lifecycle/provenance responsibilities and are not
valid canonical stores for customer configuration.

* **Model/table:** `MarketplaceInstallationAssistantConfiguration` /
  `marketplace_installation_assistant_configurations` (one row per installation).
* **Columns:** UUID `id`; non-null UUID `installation_id`; non-null JSONB
  `configuration`; non-null integer `configuration_version`; non-null UUID
  `updated_by_user_id`; non-null timestamps `created_at` and `updated_at`.
* **Defaults:** database default `1` for `configuration_version`; no fabricated
  configuration default.
* **Constraints/indexes:** primary key on `id`, unique foreign key on
  `installation_id` with `ON DELETE CASCADE`, foreign key to `tenant_users` with
  `ON DELETE RESTRICT`, and `configuration_version >= 1` check. The unique key is
  also the lookup index.
* **Legacy behavior:** existing installations receive no row. Their API response
  is explicitly `needs_configuration`, version `0`, and `configuration: null`.
* **Rollout:** deploy the additive migration first, then the compatible API. No
  speculative backfill or Flow inspection is performed.
* **Why not existing JSON:** manifest/dependency snapshots describe template
  provenance, resource metadata describes generated resources, and
  `customization_state` is reserved for future managed/customized baseline and
  drift state. Reusing any of them would create ambiguous ownership and prevent a
  clean independently-versioned atomic configuration boundary.

After review, apply with `cd backend && alembic upgrade head`.
