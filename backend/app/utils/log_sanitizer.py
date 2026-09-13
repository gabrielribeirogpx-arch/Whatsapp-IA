from __future__ import annotations

import re
from typing import Any


_SECRET_KEY = re.compile(
    r"(^|_)(password|token|access_token|refresh_token|api_key|client_secret|authorization|cookie|session_token|jwt|credential|secret)(_|$)",
    re.IGNORECASE,
)
_CONTENT_KEY = re.compile(r"(^|_)(message|body|content|text|prompt|variables|components|graph|nodes|edges|payload|response)(_|$)", re.IGNORECASE)


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
    return {
        "provider": provider,
        "event_type": payload.get("object") or payload.get("event_type") or payload.get("type"),
        "message_id": payload.get("message_id") or payload.get("wamid") or payload.get("id"),
        "status": payload.get("status"),
        "timestamp": payload.get("timestamp"),
        "top_level_keys": sorted(str(key) for key in payload.keys()),
    }
