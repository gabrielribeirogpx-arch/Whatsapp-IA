from datetime import date, datetime

import pytest

from app.routers.dashboard import _dashboard_date_range


def test_dashboard_custom_range_is_inclusive_by_calendar_day():
    start, end, days = _dashboard_date_range("7d", date(2026, 9, 1), date(2026, 9, 15))

    assert start == datetime(2026, 9, 1)
    assert end == datetime(2026, 9, 16)
    assert days == 15


def test_dashboard_custom_range_rejects_inverted_dates():
    with pytest.raises(ValueError):
        _dashboard_date_range("7d", date(2026, 9, 15), date(2026, 9, 1))


def test_dashboard_custom_range_requires_both_dates():
    with pytest.raises(ValueError):
        _dashboard_date_range("7d", date(2026, 9, 1), None)
