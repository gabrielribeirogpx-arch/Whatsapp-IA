from __future__ import annotations

import re
import hashlib
from typing import Any


_SECRET_KEY = re.compile(
    r"(^|_)(password|token|access_token|refresh_token|api_key|client_secret|authorization|cookie|session_token|jwt|credential|secret)(_|$)",
    re.IGNORECASE,
)
_CONTENT_KEY = re.compile(r"(^|_)(message|body|content|text|prompt|variables|components|graph|nodes|edges|payload|response)(_|$)", re.IGNORECASE)
_PHONE_LIKE = re.compile(r"(?<!\d)\+?\d[\d\s().-]{7,}\d(?!\d)")


def mask_phone(value: Any) -> str:
    """Mask a phone-like identifier while retaining four digits for support."""
    text = str(value or "").strip()
    digits = re.sub(r"\D", "", text)
    if not digits:
        return "n/a" if text else ""
    return f"{'*' * max(4, len(digits) - 4)}{digits[-4:]}"


def sanitize_lock_key(value: Any) -> str:
    """Redact phone-like portions of lock keys without hiding their namespace."""
    text = str(value or "")
    return _PHONE_LIKE.sub(lambda match: mask_phone(match.group(0)), text)[:200]


def stable_identifier(value: Any) -> str | None:
    """Return a short stable digest suitable for correlating external IDs."""
    text = str(value or "").strip()
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12] if text else None


def outbound_payload_context(payload: dict[str, Any]) -> dict[str, Any]:
    """Describe an outbound job without exposing recipient or message content."""
    text = payload.get("text") or payload.get("body_text") or payload.get("caption") or ""
    buttons = payload.get("buttons") or payload.get("options")
    return {
        "tenant_id": payload.get("tenant_id"),
        "job_id": payload.get("job_id"),
        "node_id": payload.get("node_id"),
        "node_type": payload.get("node_type"),
        "message_type": payload.get("message_type") or payload.get("type"),
        "text_len": len(str(text)),
        "has_buttons": bool(buttons),
        "has_media": bool(payload.get("media_url") or payload.get("media_type")),
    }


def provider_response_context(response: Any) -> dict[str, Any]:
    """Extract delivery metadata from a provider response, never the raw body."""
    data = response if isinstance(response, dict) else {}
    messages = data.get("messages") if isinstance(data.get("messages"), list) else []
    raw_message_id = data.get("message_id") or data.get("id")
    if not raw_message_id and messages and isinstance(messages[0], dict):
        raw_message_id = messages[0].get("id")
    status = data.get("status")
    success = data.get("success")
    if success is None:
        success = str(status or "").lower() not in {"failed", "error"} and bool(raw_message_id or messages)
    return {"status": status, "message_id_hash": stable_identifier(raw_message_id), "success": bool(success)}


def sanitize_for_log(value: Any, *, include_content: bool = False, depth: int = 0) -> Any:
    """Return bounded operational metadata without credentials or customer content."""
    if depth > 5:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            name = str(key)
            if _SECRET_KEY.search(name):
                result[name] = "[REDACTED]"
            elif not include_content and _CONTENT_KEY.search(name):
                if isinstance(item, (list, tuple, dict)):
                    result[f"{name}_count"] = len(item)
                elif item is not None:
                    result[f"{name}_present"] = True
            else:
                result[name] = sanitize_for_log(item, include_content=include_content, depth=depth + 1)
        return result
    if isinstance(value, (list, tuple)):
        return [sanitize_for_log(item, include_content=include_content, depth=depth + 1) for item in value[:25]]
    if isinstance(value, str):
        return value[:200]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return type(value).__name__


def webhook_log_context(payload: dict[str, Any], *, provider: str = "meta") -> dict[str, Any]:
    """Extract non-content fields useful for webhook ingestion diagnostics."""
    entries = payload.get("entry") if isinstance(payload.get("entry"), list) else []
    messages: list[dict[str, Any]] = []
    statuses: list[dict[str, Any]] = []
    for entry in entries:
        for change in entry.get("changes", []) if isinstance(entry, dict) else []:
            value = change.get("value", {}) if isinstance(change, dict) else {}
            messages.extend(value.get("messages", []) if isinstance(value.get("messages"), list) else [])
            statuses.extend(value.get("statuses", []) if isinstance(value.get("statuses"), list) else [])
    first = messages[0] if messages else {}
    first_status = statuses[0] if statuses else {}
    message_type = first.get("type") if isinstance(first, dict) else None
    return {
        "provider": provider,
        "event_type": payload.get("object") or payload.get("event_type") or payload.get("type"),
        "message_id": payload.get("message_id") or payload.get("wamid") or payload.get("id") or first.get("id") or first_status.get("id"),
        "status": payload.get("status") or first_status.get("status"),
        "top_level_keys": sorted(str(key) for key in payload.keys()),
        "entry_count": len(entries),
        "message_count": len(messages),
        "has_text": message_type == "text",
        "has_interactive": message_type == "interactive",
    }
