from __future__ import annotations

import re
from typing import Any

SENSITIVE_KEY_RE = re.compile(r"(authorization|bearer|api[-_]?key|secret|token|cookie|password|headers?|encrypted|webhook_payload|payload|prompt)", re.I)
SENSITIVE_VALUE_RE = re.compile(r"(Bearer\s+[A-Za-z0-9._~+/=-]+|sk-[A-Za-z0-9_-]{12,}|api[_-]?key\s*[:=])", re.I)


def sanitize_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 6:
        return "[truncated]"
    if isinstance(value, dict):
        clean: dict[str, Any] = {}
        for key, item in value.items():
            key_s = str(key)
            if SENSITIVE_KEY_RE.search(key_s) or (isinstance(item, dict) and item.get("secret") is True):
                continue
            clean[key_s] = sanitize_value(item, depth=depth + 1)
        return clean
    if isinstance(value, (list, tuple)):
        return [sanitize_value(item, depth=depth + 1) for item in list(value)[:50]]
    if isinstance(value, str):
        text = SENSITIVE_VALUE_RE.sub("[redacted]", value)
        return text[:4000]
    return value


def sanitize_metadata(value: Any) -> dict[str, Any]:
    cleaned = sanitize_value(value if isinstance(value, dict) else {})
    return cleaned if isinstance(cleaned, dict) else {}
