"""Tenant-scoped clinic scheduling policy, Portuguese input normalization and slot generation.

This module is deliberately independent from Calendar transport: Google only receives
RFC3339 values that have already been normalized here.
"""
from __future__ import annotations
from datetime import datetime, date, time, timedelta
import re
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
DEFAULT_BUSINESS_HOURS = {day: ([{"start":"08:00","end":"12:00"},{"start":"13:00","end":"18:00"}] if day in DAYS[:5] else []) for day in DAYS}
DEFAULT_POLICY = {"timezone":"America/Sao_Paulo", "default_duration_minutes":60, "slot_interval_minutes":60, "input_mode":"exact_or_period", "business_hours":DEFAULT_BUSINESS_HOURS}

class AppointmentPolicyError(ValueError): pass

def validate_policy(value: dict[str, Any] | None) -> dict[str, Any]:
    value = value or {}
    result = {**DEFAULT_POLICY, **{k:v for k,v in value.items() if k != "business_hours"}}
    result["business_hours"] = {d: list((value.get("business_hours") or {}).get(d, DEFAULT_BUSINESS_HOURS[d])) for d in DAYS}
    try: ZoneInfo(str(result["timezone"]))
    except (ZoneInfoNotFoundError, TypeError) as exc: raise AppointmentPolicyError("Timezone IANA inválido.") from exc
    for field in ("default_duration_minutes", "slot_interval_minutes"):
        try: result[field] = int(result[field])
        except (TypeError, ValueError) as exc: raise AppointmentPolicyError(f"{field} deve ser um inteiro.") from exc
        if result[field] <= 0: raise AppointmentPolicyError(f"{field} deve ser maior que zero.")
    if result["input_mode"] != "exact_or_period": raise AppointmentPolicyError("input_mode inválido.")
    for day, periods in result["business_hours"].items():
        previous = None
        if not isinstance(periods, list): raise AppointmentPolicyError(f"Horários de {day} inválidos.")
        normalized=[]
        for period in periods:
            try: start=datetime.strptime(str(period["start"]), "%H:%M").time(); end=datetime.strptime(str(period["end"]), "%H:%M").time()
            except (KeyError, ValueError) as exc: raise AppointmentPolicyError(f"Intervalo inválido em {day}.") from exc
            if start >= end or (previous and start < previous): raise AppointmentPolicyError(f"Intervalos inválidos ou sobrepostos em {day}.")
            previous=end; normalized.append({"start":start.strftime("%H:%M"),"end":end.strftime("%H:%M")})
        result["business_hours"][day]=normalized
    return result

def policy_for_tenant(db: Any, tenant_id: Any) -> dict[str, Any]:
    from app.models.tenant_appointment_policy import TenantAppointmentPolicy
    item = db.query(TenantAppointmentPolicy).filter(TenantAppointmentPolicy.tenant_id == tenant_id).one_or_none()
    return validate_policy(item.policy_json if item else None)

def intervals_for_day(day: date, policy: dict[str, Any]) -> list[tuple[datetime,datetime]]:
    tz=ZoneInfo(policy["timezone"])
    return [(datetime.combine(day, datetime.strptime(p["start"], "%H:%M").time(), tz), datetime.combine(day, datetime.strptime(p["end"], "%H:%M").time(), tz)) for p in policy["business_hours"][DAYS[day.weekday()]]]

def normalize_preferred_period(text: str, policy: dict[str, Any], *, now: datetime | None=None) -> dict[str, Any]:
    policy=validate_policy(policy); tz=ZoneInfo(policy["timezone"]); raw=" ".join(str(text).strip().casefold().split())
    base=(now.astimezone(tz) if now and now.tzinfo else (now.replace(tzinfo=tz) if now else datetime.now(tz)))
    if not raw: raise AppointmentPolicyError("Informe uma data ou período válido.")
    if "amanhã" in raw or "amanha" in raw: target=base.date()+timedelta(days=1)
    else:
        match=re.search(r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b",raw)
        if not match: raise AppointmentPolicyError("Use uma data no formato dd/mm/aaaa.")
        try: target=date(int(match.group(3) or base.year),int(match.group(2)),int(match.group(1)))
        except ValueError as exc: raise AppointmentPolicyError("A data informada não existe.") from exc
    if target < base.date(): raise AppointmentPolicyError("Não é possível agendar em uma data passada.")
    intervals=intervals_for_day(target, policy)
    if not intervals: raise AppointmentPolicyError("A clínica está fechada nesta data.")
    # Never treat the day in dd/mm as a clock: an explicit marker or a time suffix is mandatory.
    clock=re.search(r"(?:às|\bas)\s*(\d{1,2})(?:\s*[:h]\s*(\d{2})?)?\s*(?:h)?\b", raw) or re.search(r"\b(\d{1,2})(?::(\d{2})|h)\b", raw)
    if clock:
        hour, minute=int(clock.group(1)),int(clock.group(2) or 0)
        try: start=datetime.combine(target,time(hour,minute),tz)
        except ValueError as exc: raise AppointmentPolicyError("Horário inválido.") from exc
        end=start+timedelta(minutes=policy["default_duration_minutes"])
        if not any(start>=a and end<=b for a,b in intervals): raise AppointmentPolicyError("O horário está fora do funcionamento da clínica.")
        return {"mode":"exact","start":start.isoformat(),"end":end.isoformat(),"timezone":policy["timezone"]}
    # Word boundaries matter: ``amanhã`` contains ``manhã`` but is a date, not
    # a request for the morning period.
    period=next((p for p in ("manhã","manha","tarde","noite") if re.search(rf"(?<!\w){p}(?!\w)", raw)),None)
    # Named periods are the tenant's ordered business-hour periods.  This keeps
    # their boundaries tenant-scoped instead of maintaining a second clock here.
    period_index={"manhã":0,"manha":0,"tarde":1,"noite":2}.get(period)
    if period_index is not None:
        overlap=[intervals[period_index]] if period_index < len(intervals) else []
    else:
        overlap=intervals
    if not overlap: raise AppointmentPolicyError("O período informado está fora do funcionamento da clínica.")
    return {"mode":"period","window_start":overlap[0][0].isoformat(),"window_end":overlap[-1][1].isoformat(),"timezone":policy["timezone"]}

def appointments_for_availability(*, start: str, end: str, timezone: str, busy: list[dict[str,Any]], policy: dict[str,Any], mode: str="period") -> list[dict[str,Any]]:
    policy=validate_policy(policy); tz=ZoneInfo(timezone)
    begin=datetime.fromisoformat(start).astimezone(tz); finish=datetime.fromisoformat(end).astimezone(tz)
    duration=timedelta(minutes=policy["default_duration_minutes"]); step=timedelta(minutes=policy["slot_interval_minutes"])
    blocked=[(datetime.fromisoformat(x["start"]).astimezone(tz),datetime.fromisoformat(x["end"]).astimezone(tz)) for x in busy]
    def free(a,b): return not any(a < y and b > x for x,y in blocked)
    candidates=[]
    if mode == "exact": candidates=[begin] if free(begin,finish) and any(begin>=a and finish<=b for a,b in intervals_for_day(begin.date(),policy)) else []
    else:
        current_day=begin.date()
        while current_day <= finish.date():
            for a,b in intervals_for_day(current_day,policy):
                cursor=max(a,begin)
                while cursor+duration<=min(b,finish):
                    if free(cursor,cursor+duration): candidates.append(cursor)
                    cursor+=step
            current_day+=timedelta(days=1)
    return [{"id":x.isoformat(),"label":x.strftime("%d/%m às %H:%M"),"description":f"Consulta de {policy['default_duration_minutes']} minutos","start":x.isoformat(),"end":(x+duration).isoformat(),"timezone":timezone} for x in candidates]
