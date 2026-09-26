from datetime import datetime

from app.models.flow_session import FlowSession


def test_completed_transition_sets_timestamp_once_and_reopening_preserves_it():
    session = FlowSession(status="running")
    assert session.completed_at is None

    session.status = "completed"
    first = session.completed_at
    assert isinstance(first, datetime)

    session.status = "running"
    session.status = "completed"
    assert session.completed_at == first


def test_non_completed_session_has_no_completion_timestamp():
    assert FlowSession(status="expired").completed_at is None


def test_first_abandonment_is_idempotent_and_reopening_preserves_it():
    session = FlowSession(status="running")
    assert session.abandoned_at is None

    session.status = "expired"
    first = session.abandoned_at
    assert isinstance(first, datetime)

    session.status = "running"
    session.status = "abandoned"
    assert session.abandoned_at == first


def test_legacy_final_state_does_not_invent_abandonment_timestamp():
    session = FlowSession()
    # Simulate ORM hydration: no status transition is observed by new code.
    session.__dict__["status"] = "expired"
    assert session.abandoned_at is None
