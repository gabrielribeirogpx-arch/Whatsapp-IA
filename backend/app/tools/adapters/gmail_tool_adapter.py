from __future__ import annotations

from typing import Any, Callable
from sqlalchemy.orm import Session

from app.services.gmail_service import PROVIDER, GmailService
from app.tools.base import NormalizedToolResult, ToolResult
from app.tools.context import ToolContext, sanitize_metadata

GMAIL_TOOL_IDS = {"gmail_list_messages", "gmail_search_messages", "gmail_read_message", "gmail_create_draft", "gmail_send_email"}


def gmail_tool_definitions(*, connected: bool) -> list[dict[str, Any]]:
    labels = {
        "gmail_list_messages": "[Gmail] Listar e-mails",
        "gmail_search_messages": "[Gmail] Buscar e-mails",
        "gmail_read_message": "[Gmail] Ler e-mail",
        "gmail_create_draft": "[Gmail] Criar rascunho",
        "gmail_send_email": "[Gmail] Enviar e-mail",
    }
    descriptions = {
        "gmail_send_email": "Envia e-mail pelo Gmail conectado somente após confirmação explícita do usuário.",
        "gmail_create_draft": "Cria rascunho no Gmail conectado do workspace.",
        "gmail_list_messages": "Lista mensagens do Gmail conectado do workspace.",
        "gmail_search_messages": "Busca mensagens do Gmail conectado do workspace.",
        "gmail_read_message": "Lê uma mensagem do Gmail conectado do workspace.",
    }
    return [{"id": tid, "tool_id": tid, "tool_name": tid, "display_name": labels[tid], "name": labels[tid], "description": descriptions[tid], "input_schema": {"type": "object"}, "is_enabled": connected, "server_id": None, "server_name": "Gmail conectado" if connected else "Requer conexão", "metadata": {"kind": "internal", "provider": "gmail", "source": "gmail_connected", "requires_connection": not connected}} for tid in labels]


class GmailToolAdapter:
    tool_type = "gmail"

    def __init__(self, db: Session | None = None, service_factory: Callable[[Session, Any], GmailService] | None = None) -> None:
        self.db = db
        self.service_factory = service_factory or (lambda db, tenant_id: GmailService(db, tenant_id))

    def can_execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> bool:
        return tool_id in GMAIL_TOOL_IDS and (self.db or (config or {}).get("db")) is not None and context.tenant_id is not None

    def execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> ToolResult:
        db = self.db or (config or {}).get("db")
        args = input if isinstance(input, dict) else {}
        service = self.service_factory(db, context.tenant_id)
        if tool_id == "gmail_list_messages":
            data, action = service.list_messages(**args), "list_messages"
        elif tool_id == "gmail_search_messages":
            data, action = service.search_messages(**args), "search_messages"
        elif tool_id == "gmail_read_message":
            data, action = service.read_message(**args), "read_message"
        elif tool_id == "gmail_create_draft":
            data, action = service.create_draft(**args), "create_draft"
        elif tool_id == "gmail_send_email":
            data, action = service.send_email(**args), "send_email"
        else:
            data, action = {"ok": False, "message": "Ferramenta Gmail não encontrada."}, "unknown"
        ok = data.get("ok") is True
        normalized = NormalizedToolResult(ok, tool_id, type=f"gmail.{action}", summary="Operação do Gmail concluída" if ok else str(data.get("message") or "Falha ao executar Gmail"), data=data if ok else {}, error=None if ok else {"code": str(data.get("message") or "gmail_error")})
        return ToolResult(ok, self.tool_type, tool_id=tool_id, tool_name=tool_id, output=sanitize_metadata(data), structured_content={"ok": ok, "tool": tool_id, "result": sanitize_metadata(data) if ok else {}, "error": None if ok else data.get("message")}, error_code=None if ok else "gmail_error", metadata={"provider": PROVIDER, "source": "integration_connections"}, normalized_result=normalized)
