from datetime import datetime, timedelta

from app.services.dashboard_metrics import (
    _canonical_channel,
    get_abandonment_rate,
    get_response_rate,
    metric_delta,
    response_cycle_delays,
)


START = datetime(2026, 9, 1)
END = datetime(2026, 9, 8)


class _Result:
    def __init__(self, value):
        self.value = value

    def scalar(self):
        return self.value


class _ScalarSession:
    def __init__(self, *values):
        self.values = iter(values)
        self.statements = []

    def execute(self, statement):
        self.statements.append(statement)
        return _Result(next(self.values))


def test_response_rate_is_conversation_based_and_bounded():
    db = _ScalarSession(10, 8)

    rate, responded, inbound = get_response_rate(db, "tenant-a", START, END)

    assert (rate, responded, inbound) == (80.0, 8, 10)
    assert all("tenant_id" in str(statement) for statement in db.statements)


def test_response_rate_without_inbound_is_unavailable():
    assert get_response_rate(_ScalarSession(0, 0), "tenant-a", START, END) == (None, 0, 0)


def test_response_cycles_keep_first_inbound_and_ignore_outbound_without_wait():
    rows = [
        ("a", START - timedelta(minutes=1), True),
        ("a", START, False),
        ("a", START + timedelta(minutes=1), False),
        ("a", START + timedelta(minutes=2), False),
        ("a", START + timedelta(minutes=5), True),
        ("a", START + timedelta(minutes=6), True),
        ("a", START + timedelta(minutes=10), False),
        ("a", END + timedelta(minutes=5), True),
    ]

    assert response_cycle_delays(rows, START, END) == [300.0, (END + timedelta(minutes=5) - (START + timedelta(minutes=10))).total_seconds()]


def test_inbound_after_window_does_not_start_response_cycle():
    rows = [("a", END, False), ("a", END + timedelta(minutes=2), True)]
    assert response_cycle_delays(rows, START, END) == []


def test_abandonment_uses_one_created_at_cohort_and_never_exceeds_100():
    db = _ScalarSession(4, 4)
    rate, abandoned, started = get_abandonment_rate(db, "tenant-a", START, END)

    assert (rate, abandoned, started) == (100.0, 4, 4)
    statements = [str(statement) for statement in db.statements]
    assert all("created_at" in statement and "tenant_id" in statement for statement in statements)


def test_abandonment_without_sessions_is_unavailable():
    assert get_abandonment_rate(_ScalarSession(0, 0), "tenant-a", START, END) == (None, 0, 0)


def test_unknown_or_absent_channel_is_auditable_as_other():
    assert _canonical_channel(None) == "outros"
    assert _canonical_channel({"channel": "carrier-pigeon"}) == "outros"
    assert _canonical_channel({"source": "webchat"}) == "site_chat"


def test_delta_preserves_zero_and_null_sample_semantics():
    assert metric_delta(0, 10) == -100.0
    assert metric_delta(0, 0) == 0.0
    assert metric_delta(None, 10) is None
