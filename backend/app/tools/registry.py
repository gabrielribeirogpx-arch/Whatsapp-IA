from __future__ import annotations

import logging
import time
from typing import Any

from app.services.execution_budget_service import ExecutionBudgetExceeded
from app.tools.base import BaseToolAdapter, NormalizedToolResult, ToolResult
from app.tools.context import ToolContext, sanitize_metadata
from app.tools.errors import ToolNotFound, ToolRegistryError
from app.observability import TraceContext, TraceEventType, record_event

logger = logging.getLogger(__name__)


class ToolRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, BaseToolAdapter] = {}

    def register(self, adapter: BaseToolAdapter) -> None:
        tool_type = str(getattr(adapter, "tool_type", "") or "").strip()
        if not tool_type:
            raise ValueError("adapter.tool_type is required")
        self._adapters[tool_type] = adapter

    def get(self, tool_type: str) -> BaseToolAdapter:
        adapter = self._adapters.get(str(tool_type))
        if adapter is None:
            raise ToolNotFound(f"Tool type not registered: {tool_type}")
        return adapter

    def execute(self, tool_type: str, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> ToolResult:
        started = time.monotonic()
        adapter = self._adapters.get(str(tool_type))
        safe = {"tenant_id": str(context.tenant_id or ""), "tool_type": str(tool_type), "tool_id": str(tool_id), "trace_id": context.trace_id, "budget_snapshot": context.budget_snapshot()}
        logger.info("event=tool_registry_execute %s", sanitize_metadata(safe))
        trace = TraceContext.from_mapping({"trace_id": context.trace_id, "tenant_id": context.tenant_id, "conversation_id": context.conversation_id, "flow_id": context.flow_id})
        record_event(None, trace, TraceEventType.TOOL_CALLED, metadata={**safe, "input": input})
        if adapter is None:
            logger.warning("event=tool_registry_blocked %s", {**safe, "error_code": "tool_not_found"})
            return ToolResult(False, str(tool_type), tool_id=str(tool_id), error_code="tool_not_found", metadata=safe, normalized_result=NormalizedToolResult(False, str(tool_id), type=str(tool_type), error={"code": "tool_not_found"}))
        try:
            budget = context.execution_budget
            if budget is not None:
                budget.checkpoint("tool_registry_start")
            if not adapter.can_execute(str(tool_id), input, context, config or {}):
                logger.warning("event=tool_registry_blocked %s", {**safe, "error_code": "tool_not_allowed"})
                return ToolResult(False, str(tool_type), tool_id=str(tool_id), error_code="tool_not_allowed", metadata=safe, normalized_result=NormalizedToolResult(False, str(tool_id), type=str(tool_type), error={"code": "tool_not_allowed"}))
            result = adapter.execute(str(tool_id), input, context, config or {})
            if result.normalized_result is None:
                result.normalized_result = NormalizedToolResult(result.ok, str(result.tool_name or result.tool_id or tool_id), type=str(tool_type), data=result.output if isinstance(result.output, dict) else {}, result_text=str(result.output) if isinstance(result.output, (str, int, float, bool)) else None, error={"code": result.error_code} if result.error_code else None)
            result.metadata = sanitize_metadata({**safe, **(result.metadata or {}), "duration_ms": int((time.monotonic() - started) * 1000)})
            logger.info("event=tool_registry_success %s", {**safe, "duration_ms": result.metadata.get("duration_ms"), "ok": result.ok, "error_code": result.error_code})
            record_event(None, trace, TraceEventType.TOOL_FINISHED, duration_ms=result.metadata.get("duration_ms"), metadata={**safe, "ok": result.ok, "error_code": result.error_code})
            return result
        except ExecutionBudgetExceeded as exc:
            if context.execution_budget is not None:
                context.execution_budget.exceeded_reason = context.execution_budget.exceeded_reason or "tool_registry"
            logger.warning("event=tool_registry_blocked %s", {**safe, "error_code": "budget_exceeded"})
            return ToolResult(False, str(tool_type), tool_id=str(tool_id), error_code="budget_exceeded", error_message=str(exc), metadata=safe, normalized_result=NormalizedToolResult(False, str(tool_id), type=str(tool_type), error={"code": "budget_exceeded"}))
        except ToolRegistryError as exc:
            code = getattr(exc, "error_code", "tool_registry_error")
            logger.warning("event=tool_registry_error %s", {**safe, "error_code": code})
            return ToolResult(False, str(tool_type), tool_id=str(tool_id), error_code=code, error_message=str(exc), metadata=safe, normalized_result=NormalizedToolResult(False, str(tool_id), type=str(tool_type), error={"code": code}))
        except Exception as exc:
            logger.exception("event=tool_registry_error tenant_id=%s tool_type=%s tool_id=%s trace_id=%s error_code=tool_execution_error", context.tenant_id, tool_type, tool_id, context.trace_id)
            return ToolResult(False, str(tool_type), tool_id=str(tool_id), error_code="tool_execution_error", error_message=type(exc).__name__, metadata=safe, normalized_result=NormalizedToolResult(False, str(tool_id), type=str(tool_type), error={"code": "tool_execution_error", "message": type(exc).__name__}))
