from __future__ import annotations

from typing import Any, Callable

from app.tools.base import NormalizedToolResult, ToolResult
from app.tools.context import ToolContext, sanitize_metadata


def _extract_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value.strip() or None
    if isinstance(value, (int, float, bool)):
        return str(value)
    if isinstance(value, list):
        parts = [_extract_text(item) for item in value]
        joined = "\n".join(part for part in parts if part)
        return joined or None
    if isinstance(value, dict):
        content = value.get("content")
        if isinstance(content, list):
            parts = [str(item.get("text") or "").strip() for item in content if isinstance(item, dict) and str(item.get("type") or "") == "text"]
            parts = [part for part in parts if part]
            if parts:
                return "\n".join(parts)
        for key in ("result_text", "text", "message", "output", "result"):
            if key in value:
                text = _extract_text(value.get(key))
                if text:
                    return text
    return None


def _extract_structured(raw: dict[str, Any], raw_result: Any) -> dict[str, Any] | None:
    if isinstance(raw_result, dict) and isinstance(raw_result.get("structuredContent"), dict):
        return raw_result.get("structuredContent")
    if isinstance(raw.get("structuredContent"), dict):
        return raw.get("structuredContent")
    return None


def normalize_mcp_tool_result(tool_id: str, raw: dict[str, Any], raw_result: Any = None) -> NormalizedToolResult:
    raw_result = raw.get("result") if raw_result is None else raw_result
    structured = _extract_structured(raw, raw_result) or {}
    raw_ok = raw.get("ok") is True
    structured_ok = structured.get("ok")
    ok = raw_ok and structured_ok is not False
    tool_name = str(structured.get("tool") or raw.get("tool_name") or tool_id)
    data = structured.get("data") if isinstance(structured.get("data"), dict) else None
    if data is None and isinstance(structured.get("result"), dict):
        data = structured.get("result")
    if data is None:
        data = {}
    error_value = structured.get("error") if "error" in structured else raw.get("error")
    error = None
    if error_value:
        error = error_value if isinstance(error_value, dict) else {"code": str(error_value)}
    return NormalizedToolResult(
        ok=ok,
        tool=tool_name,
        type=str(structured.get("type") or "").strip() or None,
        summary=str(structured.get("summary") or "").strip() or None,
        result_text=_extract_text(raw_result) or _extract_text(raw),
        data=sanitize_metadata(data),
        error=sanitize_metadata(error),
    )


class MCPToolAdapter:
    tool_type = "mcp_tool"

    def __init__(self, executor: Callable[..., dict[str, Any]] | None = None) -> None:
        self.executor = executor

    def _find(self, tool_id: str, config: dict[str, Any]) -> dict[str, Any] | None:
        return next((t for t in config.get("mcp_tools", []) if isinstance(t, dict) and str(t.get("tool_id")) == tool_id), None)

    def can_execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> bool:
        cfg = config or {}
        return cfg.get("allow_mcp_tools", True) is not False and self._find(tool_id, cfg) is not None and (self.executor or cfg.get("executor")) is not None

    def execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> ToolResult:
        cfg = config or {}
        tool = self._find(tool_id, cfg) or {}
        executor = self.executor or cfg.get("executor")
        raw = executor(tool, input if isinstance(input, dict) else {})
        raw_result = raw.get("result")
        structured_content = _extract_structured(raw, raw_result)
        if isinstance(raw.get("structuredContent"), dict) and isinstance(raw_result, dict) and "structuredContent" not in raw_result:
            raw_result = {**raw_result, "structuredContent": raw.get("structuredContent")}
        normalized = normalize_mcp_tool_result(tool_id, raw, raw_result)
        return ToolResult(
            normalized.ok,
            self.tool_type,
            tool_id=tool_id,
            tool_name=raw.get("tool_name") or tool.get("name"),
            output=sanitize_metadata(raw_result),
            structured_content=sanitize_metadata(structured_content),
            error_code=(normalized.error or {}).get("code") if normalized.error else raw.get("error"),
            metadata={"status": raw.get("status"), "latency_ms": raw.get("latency_ms"), "raw_result": sanitize_metadata(raw_result)},
            normalized_result=normalized,
        )
