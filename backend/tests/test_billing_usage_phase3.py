from pathlib import Path


def test_usage_migration_has_single_linear_parent_and_idempotency_constraint():
    migration = Path(__file__).parents[1] / "alembic/versions/20260721_billing_usage.py"
    text = migration.read_text()
    assert 'down_revision = "20260721_billing_trial"' in text
    assert "uq_usage_event_source" in text
    assert "uq_usage_counter_period" in text


def test_usage_routes_keep_path_tenant_id_and_are_read_only():
    text = (Path(__file__).parents[1] / "app/routers/billing.py").read_text()
    assert '@router.get("/usage")' in text
    assert '@admin_router.get("/tenants/{tenant_id}/usage")' in text
    assert "tenant_id: str = Path(...)" in text
    assert "UsageService(db).usage_view" in text
