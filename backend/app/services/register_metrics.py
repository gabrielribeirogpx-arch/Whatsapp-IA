"""In-process counters for the public registration funnel.

They intentionally contain no registration data, so they can be safely exported by the
application's logging/metrics integration without leaking credentials.
"""
from collections import Counter
from threading import Lock

_COUNTERS: Counter[str] = Counter()
_LOCK = Lock()


def increment(metric: str) -> None:
    with _LOCK:
        _COUNTERS[metric] += 1


def snapshot() -> dict[str, int]:
    with _LOCK:
        return dict(_COUNTERS)
