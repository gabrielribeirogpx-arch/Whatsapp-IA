from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from zoneinfo import ZoneInfo
from typing import Any

logger = logging.getLogger(__name__)

DEFAULT_RENDER_TIMEZONE = ZoneInfo("America/Sao_Paulo")

_PLACEHOLDER_RE = re.compile(
    r"{{\s*([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)\s*}}"
    r"|(?<!{){\s*([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)\s*}(?!})"
)
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
    node_id: str | None = None
    node_outputs: dict[str, Any] | None = None

    def values(self) -> dict[str, Any]:
        now = self.now or datetime.now(DEFAULT_RENDER_TIMEZONE)
        now_br = _localized_datetime(now)
        phone = self.phone or _phone_from_external_user_id(self.external_user_id)
        safe_metadata = {
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
        }
        session_values = session_runtime_values(self.session)
        variables = _public_context_values(getattr(self.session, "variables", None))
        node_outputs = _public_context_values(self.node_outputs)
        # Persisted variables are the canonical source and intentionally win over
        # safe metadata and legacy context. Outputs from the current node win last.
        values = {**session_values, **safe_metadata, **variables, **node_outputs}
        values["variables"] = {**variables, **node_outputs}
        return values


def render_template(value: Any, context: FlowRenderContext) -> Any:
    if not isinstance(value, str):
        return value
    if "{" not in value:
        return value
    if len(value) > MAX_TEMPLATE_LENGTH:
        logger.warning("[FLOW TEMPLATE] template too large length=%s", len(value))
        value = value[:MAX_TEMPLATE_LENGTH]
    values = context.values()

    resolved_keys, missing_keys = template_keys(value, values)
    logger.log(
        logging.WARNING if missing_keys else logging.INFO,
        "event=RUNTIME_V2_TEMPLATE_RENDER_INPUT node_id=%s session_id=%s "
        "render_context=%r session.variables=%r session.context=%r "
        "resolved_keys=%s missing_keys=%s",
        context.node_id,
        getattr(context.session, "id", None),
        values,
        getattr(context.session, "variables", None),
        getattr(context.session, "context", None),
        resolved_keys,
        missing_keys,
    )

    rendered_resolved_keys: list[str] = []
    rendered_missing_keys: list[str] = []

    def replace(match: re.Match[str]) -> str:
        path = match.group(1) or match.group(2)
        resolved = _resolve_path(values, path)
        if resolved is None:
            rendered_missing_keys.append(path)
            return match.group(0) if _missing_variable_behavior() == "preserve" else ""
        rendered_resolved_keys.append(path)
        return str(resolved)

    rendered = _PLACEHOLDER_RE.sub(replace, value)
    logger.log(
        logging.WARNING if rendered_missing_keys else logging.INFO,
        "event=runtime_v2_template_render node_id=%s session_id=%s template=%r "
        "resolved_keys=%s missing_keys=%s rendered_preview=%r",
        context.node_id,
        getattr(context.session, "id", None),
        _redacted_preview(value),
        sorted(set(rendered_resolved_keys)),
        sorted(set(rendered_missing_keys)),
        _redacted_preview(rendered),
    )
    if len(rendered) > MAX_RENDERED_LENGTH:
        logger.warning("[FLOW TEMPLATE] rendered value too large tenant_id=%s length=%s", context.tenant_id, len(rendered))
        return rendered[:MAX_RENDERED_LENGTH]
    return rendered


def template_keys(value: str, values: dict[str, Any]) -> tuple[list[str], list[str]]:
    """Report renderability without mutating the template."""
    keys = [match.group(1) or match.group(2) for match in _PLACEHOLDER_RE.finditer(value)]
    resolved = sorted({key for key in keys if _resolve_path(values, key) is not None})
    missing = sorted({key for key in keys if _resolve_path(values, key) is None})
    return resolved, missing


def _missing_variable_behavior() -> str:
    # Empty preserves the renderer's historical production contract. Operators
    # may opt into literal placeholders while still receiving structured logs.
    import os

    return "preserve" if os.getenv("FLOW_V2_MISSING_VARIABLE", "empty").lower() == "preserve" else "empty"


def _redacted_preview(value: str) -> str:
    return re.sub(r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b|\b\+?\d{10,15}\b", "[REDACTED]", value[:240])


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


def session_runtime_values(session: Any) -> dict[str, Any]:
    """Return the persisted values visible to both conditions and templates.

    ``variables`` is the Runtime V2 canonical store, so it must override the
    legacy ``context`` when both contain the same key.
    """
    legacy = _public_context_values(getattr(session, "context", None))
    variables = _public_context_values(getattr(session, "variables", None))
    return {**legacy, **variables}
