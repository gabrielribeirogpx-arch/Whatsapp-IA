from __future__ import annotations
from typing import Any, Callable
from app.tools.base import ToolResult
from app.tools.context import ToolContext, sanitize_metadata

class WebhookToolAdapter:
    tool_type = "webhook"
    def __init__(self, caller: Callable[..., dict[str, Any]] | None = None, validator: Callable[[dict[str, Any]], str | None] | None = None) -> None:
        self.caller = caller; self.validator = validator
    def _find(self, tool_id: str, config: dict[str, Any]) -> dict[str, Any] | None:
        return next((w for w in config.get("webhooks", []) if isinstance(w, dict) and str(w.get("id")) == tool_id), None)
    def can_execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> bool:
        cfg = config or {}; webhook = self._find(tool_id, cfg)
        if webhook is None or (self.caller or cfg.get("caller")) is None: return False
        return not (self.validator and self.validator(webhook))
    def execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> ToolResult:
        cfg = config or {}; webhook = self._find(tool_id, cfg) or {}; caller = self.caller or cfg.get("caller")
        if self.validator:
            err = self.validator(webhook)
            if err: return ToolResult(False, self.tool_type, tool_id=tool_id, error_code=err)
        raw = caller(webhook, input if isinstance(input, dict) else {}, budget=context.execution_budget, tenant_id=context.tenant_id)
        return ToolResult(raw.get("ok") is True, self.tool_type, tool_id=tool_id, output=sanitize_metadata(raw), error_code=raw.get("error"), metadata={"status_code": raw.get("status_code")})
