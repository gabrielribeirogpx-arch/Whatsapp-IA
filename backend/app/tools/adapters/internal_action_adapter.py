from __future__ import annotations
from typing import Any
from app.tools.base import ToolResult
from app.tools.context import ToolContext, sanitize_metadata

INTERNAL_ACTIONS = {"responder", "definir_variavel", "criar_evento", "consultar_crm", "criar_pedido", "enviar_email", "transferir_humano"}

class InternalActionAdapter:
    tool_type = "internal_action"
    def can_execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> bool:
        allowed = set((config or {}).get("allowed_actions") or INTERNAL_ACTIONS)
        return tool_id in INTERNAL_ACTIONS and tool_id in allowed
    def execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> ToolResult:
        return ToolResult(True, self.tool_type, tool_id=tool_id, output=sanitize_metadata(input), side_effects=[{"action": tool_id}])
