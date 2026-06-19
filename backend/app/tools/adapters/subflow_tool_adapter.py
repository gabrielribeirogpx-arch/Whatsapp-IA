from __future__ import annotations
from typing import Any, Callable
from app.tools.base import ToolResult
from app.tools.context import ToolContext, sanitize_metadata

class SubflowToolAdapter:
    tool_type = "subflow_tool"
    def __init__(self, executor: Callable[..., dict[str, Any]] | None = None) -> None:
        self.executor = executor
    def _find(self, tool_id: str, config: dict[str, Any]) -> dict[str, Any] | None:
        return next((t for t in config.get("subflow_tools", []) if isinstance(t, dict) and str(t.get("tool_id")) == tool_id), None)
    def can_execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> bool:
        cfg = config or {}
        return cfg.get("allow_subflow_tools", True) is not False and self._find(tool_id, cfg) is not None and (self.executor or cfg.get("executor")) is not None
    def execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> ToolResult:
        cfg = config or {}; tool = self._find(tool_id, cfg) or {}; executor = self.executor or cfg.get("executor")
        if cfg.get("consume_budget", True) and context.execution_budget is not None: context.execution_budget.consume_subflow_call()
        raw = executor(tool, input, str(cfg.get("reason") or "")[:200])
        return ToolResult(raw.get("status") == "success", self.tool_type, tool_id=tool_id, output=sanitize_metadata(raw.get("output")), error_code=raw.get("error"), metadata={"status": raw.get("status"), "flow_id": raw.get("flow_id"), "duration_ms": raw.get("duration_ms")})
