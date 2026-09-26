from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
import pytest
from app.services.appointment_policy_service import DAYS, AppointmentPolicyError, appointments_for_availability, normalize_appointment_lookup_period, normalize_preferred_period, validate_policy

def policy(**overrides):
    base={"timezone":"America/Sao_Paulo","default_duration_minutes":60,"slot_interval_minutes":60,"input_mode":"exact_or_period","business_hours":{"monday":[{"start":"08:00","end":"12:00"},{"start":"13:00","end":"18:00"}],"tuesday":[],"wednesday":[],"thursday":[],"friday":[],"saturday":[],"sunday":[]}}
    base.update(overrides); return validate_policy(base)
def test_normalizes_exact_and_periods_without_fixed_offset():
    p=policy(); now=datetime(2026,9,6,10,tzinfo=ZoneInfo("America/Sao_Paulo"))
    assert normalize_preferred_period("07/09/2026 às 14:00",p,now=now)["start"] == "2026-09-07T14:00:00-03:00"
    assert normalize_preferred_period("amanhã de manhã",p,now=now)["mode"] == "period"
    assert normalize_preferred_period("07/09/2026",p,now=now)["window_start"].endswith("08:00:00-03:00")
def test_rejects_bad_dates_closed_days_and_outside_hours():
    p=policy(); now=datetime(2026,9,1,tzinfo=ZoneInfo("America/Sao_Paulo"))
    for raw in ("31/02/2026", "06/09/2026", "07/09/2026 às 19h", "01/01/2020"):
        with pytest.raises(AppointmentPolicyError): normalize_preferred_period(raw,p,now=now)
def test_slots_exclude_lunch_busy_and_overlap():
    p=policy(slot_interval_minutes=30)
    slots=appointments_for_availability(start="2026-09-07T08:00:00-03:00",end="2026-09-07T18:00:00-03:00",timezone="America/Sao_Paulo",busy=[{"start":"2026-09-07T09:00:00-03:00","end":"2026-09-07T10:00:00-03:00"}],policy=p)
    assert all(not (x["start"].endswith("12:00:00-03:00") or "T12:" in x["start"]) for x in slots)
    assert all(not (x["start"] < "2026-09-07T10:00:00-03:00" and x["end"] > "2026-09-07T09:00:00-03:00") for x in slots)
    assert slots[0]["label"] == "07/09 às 08:00"
def test_policy_rejects_timezone_and_overlaps():
    with pytest.raises(AppointmentPolicyError): validate_policy({"timezone":"nope"})
    with pytest.raises(AppointmentPolicyError): policy(business_hours={"monday":[{"start":"08:00","end":"12:00"},{"start":"11:00","end":"13:00"}]})

def test_normalizes_weekday_clock_variants():
    p=policy(); now=datetime(2026,9,6,10,tzinfo=ZoneInfo("America/Sao_Paulo"))
    expected={"mode":"exact","start":"2026-09-07T10:00:00-03:00","end":"2026-09-07T11:00:00-03:00","timezone":"America/Sao_Paulo"}
    for raw in ("segunda às 10", "segunda as 10", "segunda às 10 horas", "Segunda as 10 horas", "segunda 10h"):
        assert normalize_preferred_period(raw,p,now=now) == expected
    assert normalize_preferred_period("segunda-feira às 10:30",p,now=now)["start"] == "2026-09-07T10:30:00-03:00"

def test_preserves_supported_natural_periods_and_rejects_invalid_text():
    p=policy(business_hours={day:[{"start":"08:00","end":"12:00"},{"start":"13:00","end":"18:00"}] for day in DAYS})
    now=datetime(2026,9,6,10,tzinfo=ZoneInfo("America/Sao_Paulo"))
    assert normalize_preferred_period("amanhã às 14:00",p,now=now)["mode"] == "exact"
    assert normalize_preferred_period("amanhã à tarde",p,now=now)["window_start"] == "2026-09-07T13:00:00-03:00"
    assert normalize_preferred_period("segunda de manhã",p,now=now)["window_end"] == "2026-09-07T12:00:00-03:00"
    after=normalize_preferred_period("dia 10 depois das 14h",p,now=now)
    assert (after["mode"],after["window_start"],after["window_end"]) == ("period","2026-09-10T14:00:00-03:00","2026-09-10T18:00:00-03:00")
    with pytest.raises(AppointmentPolicyError): normalize_preferred_period("qualquer coisa",p,now=now)


def test_lookup_period_resolves_explicit_relative_and_weekday_in_local_timezone():
    p=policy(business_hours={day:[{"start":"08:00","end":"12:00"},{"start":"13:00","end":"18:00"}] for day in DAYS})
    now=datetime(2026,9,26,10,tzinfo=ZoneInfo("America/Sao_Paulo"))

    explicit=normalize_appointment_lookup_period("28/09/2026",p,now=now)
    tomorrow=normalize_appointment_lookup_period("amanhã",p,now=now)
    weekday=normalize_appointment_lookup_period("próxima terça",p,now=now)

    assert explicit == {
        "mode":"period", "window_start":"2026-09-28T00:00:00-03:00",
        "window_end":"2026-09-29T00:00:00-03:00", "timezone":"America/Sao_Paulo",
    }
    assert tomorrow["window_start"] == "2026-09-27T00:00:00-03:00"
    assert weekday["window_start"] == "2026-09-29T00:00:00-03:00"
    assert datetime.fromisoformat(explicit["window_start"]) < datetime.fromisoformat(explicit["window_end"])
    assert datetime.fromisoformat(explicit["window_end"]) - datetime.fromisoformat(explicit["window_start"]) < timedelta(days=90)


def test_lookup_period_preserves_canonical_day_period_and_rejects_ambiguity():
    p=policy(business_hours={day:[{"start":"08:00","end":"12:00"},{"start":"13:00","end":"18:00"}] for day in DAYS})
    now=datetime(2026,9,26,10,tzinfo=ZoneInfo("America/Sao_Paulo"))

    afternoon=normalize_appointment_lookup_period("terça à tarde",p,now=now)
    assert afternoon["window_start"] == "2026-09-29T13:00:00-03:00"
    assert afternoon["window_end"] == "2026-09-29T18:00:00-03:00"
    for raw in ("um dia desses", "a consulta antiga", "quando marquei"):
        with pytest.raises(AppointmentPolicyError):
            normalize_appointment_lookup_period(raw,p,now=now)


def test_next_weekday_on_same_weekday_means_following_week():
    p=policy(business_hours={day:[{"start":"08:00","end":"18:00"}] for day in DAYS})
    now=datetime(2026,9,29,10,tzinfo=ZoneInfo("America/Sao_Paulo"))
    result=normalize_appointment_lookup_period("próxima terça",p,now=now)
    assert result["window_start"] == "2026-10-06T00:00:00-03:00"
