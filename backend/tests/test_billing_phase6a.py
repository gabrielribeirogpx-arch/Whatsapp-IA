from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")


def test_stripe_is_disabled_and_unconfigured_by_default():
    from app.core.config import settings

    assert settings.stripe_enabled is False
    assert settings.stripe_configured is False


def test_stripe_adapter_does_not_import_sdk_until_a_call():
    import sys as loaded_modules
    from app.billing.stripe_provider import StripeBillingProvider

    StripeBillingProvider()
    assert "stripe" not in loaded_modules.modules


def test_prelaunch_health_and_consistency_routes_are_present():
    source = (Path(__file__).parents[1] / "app/routers/billing.py").read_text()
    assert '@admin_router.get("/health")' in source
    assert '"not_configured"' in source
    assert '@admin_router.get("/consistency")' in source
    assert '@admin_router.get("/operations")' in source
    assert "settings.stripe_configured" in source


def test_consistency_checker_skips_stripe_when_not_configured():
    from app.services.billing_consistency_service import BillingConsistencyService

    class EmptyDb:
        def execute(self, _query):
            class Result:
                def scalars(self):
                    return self
                def all(self):
                    return []
            return Result()

    report = BillingConsistencyService(EmptyDb()).check()
    assert report["healthy"] is True
    assert report["stripe"]["status"] == "skipped_not_configured"
