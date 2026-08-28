from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.tools.context import sanitize_metadata, ToolContext


@dataclass(slots=True)
class NormalizedToolResult:
    ok: bool
    tool: str
    type: str | None = None
    summary: str | None = None
    result_text: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "tool": self.tool,
            "type": self.type,
            "summary": self.summary,
            "result_text": self.result_text,
            "data": sanitize_metadata(self.data),
            "error": sanitize_metadata(self.error),
        }


@dataclass(slots=True)
class ToolResult:
    ok: bool
    tool_type: str
    tool_id: str | None = None
    tool_name: str | None = None
    output: Any = None
    structured_content: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    usage: dict[str, Any] = field(default_factory=dict)
    side_effects: list[dict[str, Any]] = field(default_factory=list)
    normalized_result: NormalizedToolResult | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "tool_type": self.tool_type,
            "tool_id": self.tool_id,
            "tool_name": self.tool_name,
            "output": sanitize_metadata(self.output),
            "structured_content": sanitize_metadata(self.structured_content),
            "error_code": self.error_code,
            "error_message": self.error_message,
            "metadata": sanitize_metadata(self.metadata),
            "usage": sanitize_metadata(self.usage),
            "side_effects": sanitize_metadata(self.side_effects),
            "normalized_result": self.normalized_result.to_dict() if self.normalized_result else None,
        }


def invalid_tool_result(*, tool_type: str, tool_id: str, message: str = "Adapter returned an invalid ToolResult.") -> ToolResult:
    """Build the canonical failure result for adapters that violate the contract.

    ToolRegistry is the boundary between third-party adapters and callers.  Keeping
    this conversion here means callers never need to probe arbitrary result
    attributes (and, consequently, cannot leak an AttributeError into a flow).
    """
    return ToolResult(
        False,
        tool_type,
        tool_id=tool_id,
        error_code="invalid_tool_result",
        error_message=message,
        normalized_result=NormalizedToolResult(False, tool_id, type=tool_type, error={"code": "invalid_tool_result"}),
    )


def require_tool_result(result: Any, *, tool_type: str, tool_id: str) -> ToolResult:
    """Return a contract-compliant result, converting malformed adapter output."""
    if isinstance(result, ToolResult) and isinstance(result.ok, bool):
        return result
    return invalid_tool_result(tool_type=tool_type, tool_id=tool_id)


class BaseToolAdapter(Protocol):
    tool_type: str

    def can_execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> bool: ...
    def execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> ToolResult: ...
