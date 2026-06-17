from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_RENDER_TIMEZONE = ZoneInfo("America/Sao_Paulo")

_PLACEHOLDER_RE = re.compile(r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)\s*}}")
MAX_TEMPLATE_LENGTH = 20_000
MAX_RENDERED_LENGTH = 50_000


@dataclass(frozen=True)
class FlowRenderContext:
    tenant_id: Any
    external_user_id: str | None = None
    phone: str | None = None
    contact: Any | None = None
    conversation: Any | None = None
    lead: Any | None = None
    last_message: str | None = None
    now: datetime | None = None
    today: str | None = None
    flow: Any | None = None
    session: Any | None = None

    def values(self) -> dict[str, Any]:
        now = self.now or datetime.now(DEFAULT_RENDER_TIMEZONE)
        now_br = _localized_datetime(now)
        phone = self.phone or _phone_from_external_user_id(self.external_user_id)
        return {
            "tenant_id": self.tenant_id,
            "external_user_id": self.external_user_id,
            "phone": phone,
            "contact": _object_map(self.contact, ("id", "name", "phone", "email")),
            "conversation": _object_map(self.conversation, ("id", "mode", "status", "phone_number", "name")),
            "lead": _object_map(self.lead, ("id", "name", "phone", "stage", "status")),
            "last_message": self.last_message or "",
            "now": now_br.strftime("%d/%m/%Y %H:%M"),
            "today": self.today or now_br.strftime("%d/%m/%Y"),
            "now_iso": now.isoformat(),
            "today_iso": now_br.date().isoformat(),
            "flow": _object_map(self.flow, ("id", "name")),
            "session": _object_map(self.session, ("id",)),
            **(_public_context_values(getattr(self.session, "context", None))),
        }


def render_template(value: Any, context: FlowRenderContext) -> Any:
    if not isinstance(value, str):
        return value
    if "{{" not in value:
        return value
    if len(value) > MAX_TEMPLATE_LENGTH:
        logger.warning("[FLOW TEMPLATE] template too large length=%s", len(value))
        value = value[:MAX_TEMPLATE_LENGTH]
    values = context.values()

    def replace(match: re.Match[str]) -> str:
        path = match.group(1)
        resolved = _resolve_path(values, path)
        if resolved is None:
            logger.warning("[FLOW TEMPLATE] unknown placeholder tenant_id=%s placeholder=%s", context.tenant_id, path)
            return ""
        return str(resolved)

    rendered = _PLACEHOLDER_RE.sub(replace, value)
    if len(rendered) > MAX_RENDERED_LENGTH:
        logger.warning("[FLOW TEMPLATE] rendered value too large tenant_id=%s length=%s", context.tenant_id, len(rendered))
        return rendered[:MAX_RENDERED_LENGTH]
    return rendered


def _resolve_path(values: dict[str, Any], path: str) -> Any:
    current: Any = values
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _object_map(obj: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if obj is None:
        return {}
    result: dict[str, Any] = {}
    for field in fields:
        value = obj.get(field) if isinstance(obj, dict) else getattr(obj, field, None)
        if value is not None:
            result[field] = value
    return result


def _phone_from_external_user_id(external_user_id: str | None) -> str:
    raw = str(external_user_id or "")
    return raw.split(":", 1)[1] if ":" in raw else raw


def _localized_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC).astimezone(DEFAULT_RENDER_TIMEZONE)
    return value.astimezone(DEFAULT_RENDER_TIMEZONE)


def _public_context_values(context: Any) -> dict[str, Any]:
    return context if isinstance(context, dict) else {}
