from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo


def locale_name(locale: str) -> str:
    return "en-US" if locale == "en-US" else "pt-BR"


def date(value: datetime, timezone_name: str, locale: str = "pt-BR") -> str:
    try:
        value = value.replace(tzinfo=value.tzinfo or ZoneInfo("UTC")).astimezone(ZoneInfo(timezone_name))
    except Exception:
        pass
    if locale == "en-US":
        return value.strftime("%m/%d/%Y %H:%M")
    return value.strftime("%d/%m/%Y %H:%M")


def number(value: float | int | None, locale: str = "pt-BR", digits: int = 0) -> str:
    if value is None:
        return "Não disponível" if locale == "pt-BR" else "Unavailable"
    raw = f"{value:,.{digits}f}"
    return raw.replace(",", "X").replace(".", ",").replace("X", ".") if locale == "pt-BR" else raw


def duration(value: int | None, locale: str = "pt-BR") -> str:
    if value is None:
        return number(None, locale)
    if value >= 1000:
        return f"{number(value / 1000, locale, 2)} s"
    return f"{number(value, locale)} ms"


def percent(value: float | int | None, locale: str = "pt-BR") -> str:
    return f"{number(value, locale, 2).rstrip('0').rstrip(',')}%" if value is not None else number(None, locale)
