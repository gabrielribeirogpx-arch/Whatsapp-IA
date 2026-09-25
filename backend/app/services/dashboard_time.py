"""Canonical UTC time-window handling for dashboard endpoints.

Dashboard timestamps are currently stored and queried as naive UTC datetimes.  The
``timezone`` field intentionally makes that effective timezone explicit and leaves
the resolver ready for a tenant timezone in a later phase, without a migration.
All bounds use half-open semantics: ``[start, end)``.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal


PRESET_DURATIONS = {
    "24h": timedelta(hours=24),
    "7d": timedelta(hours=168),
    "30d": timedelta(hours=720),
    "90d": timedelta(hours=2160),
}


@dataclass(frozen=True)
class DashboardTimeRange:
    current_start: datetime
    current_end: datetime
    previous_start: datetime
    previous_end: datetime
    timezone: str
    mode: Literal["preset", "custom"]
    bucket_count: int


def resolve_dashboard_time_range(
    period: str = "7d",
    start_date: date | None = None,
    end_date: date | None = None,
    *,
    now: datetime | None = None,
) -> DashboardTimeRange:
    """Resolve consecutive current/previous dashboard windows in effective UTC."""
    if start_date is not None or end_date is not None:
        if start_date is None or end_date is None or end_date < start_date:
            raise ValueError("start_date and end_date must define a valid range")
        current_start = datetime.combine(start_date, time.min)
        current_end = datetime.combine(end_date + timedelta(days=1), time.min)
        mode: Literal["preset", "custom"] = "custom"
        bucket_count = (end_date - start_date).days + 1
    else:
        duration = PRESET_DURATIONS.get(period, PRESET_DURATIONS["7d"])
        current_end = now if now is not None else datetime.utcnow()
        current_start = current_end - duration
        mode = "preset"
        bucket_count = int(duration.total_seconds() // 86400)

    duration = current_end - current_start
    return DashboardTimeRange(
        current_start=current_start,
        current_end=current_end,
        previous_start=current_start - duration,
        previous_end=current_start,
        timezone="UTC",
        mode=mode,
        bucket_count=bucket_count,
    )


def percentage_delta(current: int, previous: int) -> float | None:
    """Return a real period delta; growth from zero is mathematically undefined."""
    if previous == 0:
        return 0.0 if current == 0 else None
    return round(((current - previous) / previous) * 100, 2)


def iter_daily_buckets(window: DashboardTimeRange):
    """Yield UTC daily buckets clipped to the exact current half-open window."""
    bucket_start = window.current_start
    while bucket_start < window.current_end:
        next_midnight = datetime.combine(bucket_start.date() + timedelta(days=1), time.min)
        bucket_end = min(next_midnight, window.current_end)
        yield bucket_start, bucket_end
        bucket_start = bucket_end
