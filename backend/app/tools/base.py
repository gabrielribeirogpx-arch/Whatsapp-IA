from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from app.tools.context import sanitize_metadata, ToolContext


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
        }


class BaseToolAdapter(Protocol):
    tool_type: str

    def can_execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> bool: ...
    def execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> ToolResult: ...
