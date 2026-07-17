from datetime import datetime

import pytest

from app.routers.whatsapp_campaigns import _analytics_bounds, _rate, normalize_campaign_failure
from fastapi import HTTPException


def test_campaign_analytics_rate_division_by_zero_returns_none():
    assert _rate(10, 0) is None
    assert _rate(5, 10) == 50.0


def test_campaign_analytics_invalid_interval_raises_400():
    with pytest.raises(HTTPException):
        _analytics_bounds("2026-01-02T00:00:00", "2026-01-01T00:00:00")


def test_campaign_failure_normalization_preserves_friendly_category():
    result = normalize_campaign_failure("failed_missing_variable", "Missing parameter {{1}}")
    assert result["category"] == "Variável ausente ou inválida"
    assert "variáveis" in result["recommendation"].lower()
