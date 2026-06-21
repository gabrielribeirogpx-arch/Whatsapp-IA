from __future__ import annotations

import logging
from typing import Any, Callable
from sqlalchemy.orm import Session

from app.services.suitable_service import PROVIDER, SuitableService
from app.tools.base import NormalizedToolResult, ToolResult
from app.tools.context import ToolContext, sanitize_metadata

logger = logging.getLogger(__name__)
SUITABLE_TOOL_IDS = {"suitable_check_key", "suitable_create_order"}


def suitable_tool_definitions(*, connected: bool) -> list[dict[str, Any]]:
    labels = {"suitable_check_key": "[Suitable] Validar API Key", "suitable_create_order": "[Suitable] Criar pedido"}
    desc = {"suitable_check_key": "Valida a API Key Suitable conectada ao workspace.", "suitable_create_order": "Cria pedido na Suitable somente após confirmação explícita do usuário."}
    return [{"id": tid, "tool_id": tid, "tool_name": tid, "display_name": labels[tid], "name": labels[tid], "description": desc[tid], "input_schema": {"type": "object"}, "is_enabled": connected, "server_id": None, "server_name": "Suitable conectado" if connected else "Requer conexão", "metadata": {"kind": "internal", "provider": PROVIDER, "source": "suitable_connected", "requires_connection": not connected, "server_name": "suitable-mcp"}} for tid in labels]


class SuitableToolAdapter:
    tool_type = "suitable"

    def __init__(self, db: Session | None = None, service_factory: Callable[[Session, Any], SuitableService] | None = None) -> None:
        self.db = db
        self.service_factory = service_factory or (lambda db, tenant_id: SuitableService(db, tenant_id))

    def can_execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> bool:
        return tool_id in SUITABLE_TOOL_IDS and (self.db or (config or {}).get("db")) is not None and context.tenant_id is not None

    def execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> ToolResult:
        db = self.db or (config or {}).get("db")
        args = input if isinstance(input, dict) else {}
        service = self.service_factory(db, context.tenant_id)
        logger.info("event=SUITABLE_TOOL_START tenant_id=%s conversation_id=%s tool_name=%s status=start execution_id=%s", context.tenant_id, context.conversation_id, tool_id, (context.metadata or {}).get("execution_id"))
        if tool_id == "suitable_check_key":
            data, action = service.check_key(), "check_key"
            ok = data.get("success") is True
        elif tool_id == "suitable_create_order":
            data, action = service.create_order(**args), "create_order"
            ok = data.get("ok") is True
        else:
            data, action, ok = {"ok": False, "message": "Ferramenta Suitable não encontrada."}, "unknown", False
        normalized = NormalizedToolResult(ok, tool_id, type=f"suitable.{action}", summary="Operação da Suitable concluída" if ok else str(data.get("message") or "Falha ao executar Suitable"), data=sanitize_metadata(data) if ok else {}, error=None if ok else {"code": str(data.get("message") or "suitable_error")})
        return ToolResult(ok, self.tool_type, tool_id=tool_id, tool_name=tool_id, output=sanitize_metadata(data), structured_content={"ok": ok, "tool": tool_id, "result": sanitize_metadata(data) if ok else {}, "error": None if ok else data.get("message")}, error_code=None if ok else "suitable_error", metadata={"provider": PROVIDER, "source": "integration_connections"}, normalized_result=normalized)
