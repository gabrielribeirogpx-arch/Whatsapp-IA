from datetime import date, datetime, timedelta

import pytest

from app.services.dashboard_time import (
    iter_daily_buckets,
    percentage_delta,
    resolve_dashboard_time_range,
)


NOW = datetime(2026, 9, 25, 15, 30)


@pytest.mark.parametrize(
    ("preset", "duration"),
    [("24h", timedelta(hours=24)), ("7d", timedelta(hours=168)),
     ("30d", timedelta(hours=720)), ("90d", timedelta(hours=2160))],
)
def test_presets_have_consecutive_equal_windows(preset, duration):
    window = resolve_dashboard_time_range(preset, now=NOW)

    assert window.current_end == NOW
    assert window.current_end - window.current_start == duration
    assert window.previous_end - window.previous_start == duration
    assert window.previous_end == window.current_start
    assert window.current_end == window.previous_end + duration
    assert window.previous_end <= window.current_start
    assert window.timezone == "UTC"
    assert window.mode == "preset"


def test_custom_range_includes_last_calendar_day_and_has_real_previous_window():
    window = resolve_dashboard_time_range(
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 15)
    )

    assert window.current_start == datetime(2026, 9, 1)
    assert window.current_end == datetime(2026, 9, 16)
    assert window.previous_start == datetime(2026, 8, 17)
    assert window.previous_end == window.current_start
    assert window.current_end - window.current_start == window.previous_end - window.previous_start
    assert window.bucket_count == 15
    assert window.mode == "custom"


def test_custom_sao_paulo_dates_are_civil_days_converted_to_utc():
    window = resolve_dashboard_time_range(
        start_date=date(2026, 9, 1), end_date=date(2026, 9, 15),
        timezone_name="America/Sao_Paulo",
    )
    assert window.current_start == datetime(2026, 9, 1, 3)
    assert window.current_end == datetime(2026, 9, 16, 3)
    assert window.timezone == "America/Sao_Paulo"


@pytest.mark.parametrize(
    ("timezone_name", "day", "hours"),
    [
        ("America/New_York", date(2026, 3, 8), 23),
        ("Europe/Lisbon", date(2026, 3, 29), 23),
    ],
)
def test_custom_one_day_observes_iana_dst_transition(timezone_name, day, hours):
    window = resolve_dashboard_time_range(
        start_date=day, end_date=day, timezone_name=timezone_name,
    )
    assert window.current_end - window.current_start == timedelta(hours=hours)
    buckets = list(iter_daily_buckets(window))
    assert buckets == [(window.current_start, window.current_end)]


def test_invalid_timezone_is_rejected():
    with pytest.raises(ValueError, match="IANA"):
        resolve_dashboard_time_range(timezone_name="UTC-3")


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [(13, 26, -50.0), (13, 13, 0.0), (0, 13, -100.0),
     (0, 0, 0.0), (13, 0, None)],
)
def test_percentage_delta(current, previous, expected):
    assert percentage_delta(current, previous) == expected


def test_clipped_buckets_cover_moving_window_exactly_across_midnight():
    window = resolve_dashboard_time_range("24h", now=datetime(2026, 9, 25, 15))
    buckets = list(iter_daily_buckets(window))

    assert buckets == [
        (datetime(2026, 9, 24, 15), datetime(2026, 9, 25)),
        (datetime(2026, 9, 25), datetime(2026, 9, 25, 15)),
    ]
    assert sum((end - start for start, end in buckets), timedelta()) == timedelta(hours=24)
    events = [datetime(2026, 9, 24, 14, 59), datetime(2026, 9, 24, 15),
              datetime(2026, 9, 25, 14, 59), datetime(2026, 9, 25, 15)]
    bucket_total = sum(
        sum(start <= event < end for event in events) for start, end in buckets
    )
    kpi_total = sum(window.current_start <= event < window.current_end for event in events)
    assert bucket_total == kpi_total == 2
