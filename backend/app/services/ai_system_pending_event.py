"""Shared helpers for AI System pending calendar events."""
from __future__ import annotations

import re
from typing import Any

PENDING_EVENT_KEYS = (
    "pending_event",
    "pending_calendar_event",
    "partial_calendar_event",
    "pending_google_calendar_create_event",
)


def pending_event_lookup(context: dict[str, Any] | None) -> tuple[str | None, dict[str, Any] | None]:
    if not isinstance(context, dict):
        return None, None
    for key in PENDING_EVENT_KEYS:
        value = context.get(key)
        if isinstance(value, dict):
            return key, value
    return None, None


def set_pending_event(context: dict[str, Any], payload: dict[str, Any]) -> None:
    context["pending_event"] = payload
    context["pending_calendar_event"] = payload
    context["partial_calendar_event"] = payload
    context["pending_google_calendar_create_event"] = payload


def clear_pending_event(context: dict[str, Any] | None) -> None:
    if not isinstance(context, dict):
        return
    for key in PENDING_EVENT_KEYS:
        context.pop(key, None)


def message_has_date_or_time(message: str) -> bool:
    text = (message or "").strip().lower()
    if not text:
        return False
    patterns = (
        r"\b(?:hoje|amanh[ãa]|depois\s+de\s+amanh[ãa])\b",
        r"\b\d{1,2}[:h]\d{0,2}\b",
        r"\b(?:às|as)\s*\d{1,2}\b",
        r"\b\d{1,2}\s+horas\b",
        r"\b\d{1,2}/\d{1,2}(?:/\d{2,4})?\b",
    )
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)
