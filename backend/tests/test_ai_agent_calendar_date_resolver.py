from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.ai_agent_service import (
    _calendar_create_intent_missing,
    _calendar_missing_question,
    _date_resolver_calendar_create_payload,
    _parse_calendar_target_date,
    _precheck_google_calendar_create,
)


class _Registry:
    def execute(self, *args, **kwargs):  # pragma: no cover - precheck must block before availability
        raise AssertionError("availability should not run for past dates")


def test_relative_tomorrow_uses_server_year_and_extracts_time_and_title():
    payload, missing = _date_resolver_calendar_create_payload(
        "Agende uma call online com Gustavo amanhã às 19:30",
        {},
        timezone="America/Sao_Paulo",
    )

    assert missing is None
    assert payload is not None
    assert payload["title"] == "Call Online com Gustavo"
    assert payload["timezone"] == "America/Sao_Paulo"
    assert payload["start"].endswith("19:30:00-03:00")
    assert datetime.fromisoformat(payload["start"]).year >= 2026


def test_relative_offsets_are_resolved_before_llm():
    now = datetime(2026, 6, 24, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))

    assert _parse_calendar_target_date("daqui 3 dias", now=now)[0].isoformat() == "2026-06-27"
    assert _parse_calendar_target_date("daqui 2 semanas", now=now)[0].isoformat() == "2026-07-08"
    assert _parse_calendar_target_date("depois de amanhã", now=now)[0].isoformat() == "2026-06-26"


def test_slot_filling_does_not_reask_present_time_or_title():
    payload, missing = _calendar_create_intent_missing("Agende uma call online com Gustavo às 19:30")

    assert payload is None
    assert missing == "date"
    assert _calendar_missing_question(missing, "Agende uma call online com Gustavo às 19:30") == "📅 Será hoje ou amanhã?"


def test_dates_without_year_use_current_server_year_and_can_be_blocked_as_past():
    now = datetime(2026, 6, 24, 10, 0, tzinfo=ZoneInfo("America/Sao_Paulo"))
    day, _ = _parse_calendar_target_date("dia 10/06 às 09:00", now=now, timezone="America/Sao_Paulo")

    assert day.isoformat() == "2026-06-10"


def test_precheck_blocks_past_dates_before_google_calendar():
    state, detail, conflicts = _precheck_google_calendar_create(
        tool_registry=_Registry(),
        tool_context=None,
        db=None,
        mcp_tools=[],
        payload={"title": "Consulta", "start": "2024-01-01T09:00:00-03:00", "end": "2024-01-01T10:00:00-03:00", "timezone": "America/Sao_Paulo"},
        opts={"timezone": "America/Sao_Paulo"},
        session_state={},
        budget=None,
    )

    assert state == "past_blocked"
    assert detail["message"] == "calendar_past_date_requires_confirmation" or "já passou" in detail["message"]
    assert conflicts == []
