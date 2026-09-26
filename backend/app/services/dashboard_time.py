"""Canonical tenant-aware time-window handling for dashboard endpoints.

Database timestamps remain naive UTC. Custom ranges represent civil tenant days;
presets remain absolute moving durations. All bounds are half-open: ``[start,end)``.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


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
    timezone_name: str = "UTC",
) -> DashboardTimeRange:
    """Resolve windows as naive UTC using an IANA tenant timezone.

    Presets remain absolute moving durations. Custom bounds are tenant civil days.
    """
    try:
        tenant_tz = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError("timezone must be a valid IANA timezone") from exc
    if start_date is not None or end_date is not None:
        if start_date is None or end_date is None or end_date < start_date:
            raise ValueError("start_date and end_date must define a valid range")
        current_start = _naive_utc(datetime.combine(start_date, time.min, tenant_tz))
        current_end = _naive_utc(datetime.combine(end_date + timedelta(days=1), time.min, tenant_tz))
        mode: Literal["preset", "custom"] = "custom"
        bucket_count = (end_date - start_date).days + 1
    else:
        duration = PRESET_DURATIONS.get(period, PRESET_DURATIONS["7d"])
        current_end = now if now is not None else datetime.utcnow()
        current_start = current_end - duration
        mode = "preset"
        bucket_count = int(duration.total_seconds() // 86400)

    duration = current_end - current_start
    if mode == "custom":
        previous_local_end = datetime.combine(start_date, time.min, tenant_tz)
        previous_start = _naive_utc(previous_local_end - timedelta(days=bucket_count))
        previous_end = _naive_utc(previous_local_end)
    else:
        previous_start = current_start - duration
        previous_end = current_start
    return DashboardTimeRange(
        current_start=current_start,
        current_end=current_end,
        previous_start=previous_start,
        previous_end=previous_end,
        timezone=timezone_name,
        mode=mode,
        bucket_count=bucket_count,
    )


def percentage_delta(current: int, previous: int) -> float | None:
    """Return a real period delta; growth from zero is mathematically undefined."""
    if previous == 0:
        return 0.0 if current == 0 else None
    return round(((current - previous) / previous) * 100, 2)


def _naive_utc(value: datetime) -> datetime:
    from datetime import timezone
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def local_date_for_utc(value: datetime, timezone_name: str) -> date:
    """Return the tenant civil date for a naive UTC database timestamp."""
    from datetime import timezone
    return value.replace(tzinfo=timezone.utc).astimezone(ZoneInfo(timezone_name)).date()


def iter_daily_buckets(window: DashboardTimeRange):
    """Yield UTC query bounds split at tenant-local midnights."""
    bucket_start = window.current_start
    tenant_tz = ZoneInfo(window.timezone)
    while bucket_start < window.current_end:
        local_day = local_date_for_utc(bucket_start, window.timezone)
        next_midnight = _naive_utc(datetime.combine(local_day + timedelta(days=1), time.min, tenant_tz))
        bucket_end = min(next_midnight, window.current_end)
        yield bucket_start, bucket_end
        bucket_start = bucket_end
