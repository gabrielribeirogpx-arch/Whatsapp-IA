from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

SENSITIVE_KEY_RE = re.compile(r"(authorization|api[-_]?key|apikey|token|secret|password|cookie|prompt)", re.I)


def sanitize_metadata(value: Any, *, depth: int = 0, limit: int = 1200) -> Any:
    if depth > 5:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {str(k): ("[REDACTED]" if SENSITIVE_KEY_RE.search(str(k)) else sanitize_metadata(v, depth=depth + 1, limit=limit)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_metadata(v, depth=depth + 1, limit=limit) for v in value[:25]]
    if isinstance(value, str):
        return value[:limit]
    return value


@dataclass(slots=True)
class ToolContext:
    tenant_id: Any | None = None
    conversation_id: Any | None = None
    session_id: Any | None = None
    flow_id: Any | None = None
    flow_version_id: Any | None = None
    node_id: Any | None = None
    external_user_id: str | None = None
    provider_id: Any | None = None
    phone_number_id: str | None = None
    execution_budget: Any | None = None
    trace_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def safe_metadata(self) -> dict[str, Any]:
        return sanitize_metadata(self.metadata if isinstance(self.metadata, dict) else {})

    def budget_snapshot(self) -> dict[str, Any]:
        return self.execution_budget.safe_metadata() if self.execution_budget is not None and hasattr(self.execution_budget, "safe_metadata") else {}
