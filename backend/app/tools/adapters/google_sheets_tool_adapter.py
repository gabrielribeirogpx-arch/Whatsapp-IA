from __future__ import annotations
from typing import Any, Callable
from sqlalchemy.orm import Session
from app.services.google_sheets_service import PROVIDER, GoogleSheetsService
from app.tools.base import NormalizedToolResult, ToolResult
from app.tools.context import ToolContext, sanitize_metadata

GOOGLE_SHEETS_TOOL_IDS = {"google_sheets_list_spreadsheets", "google_sheets_read_sheet", "google_sheets_append_row", "google_sheets_update_row", "google_sheets_create_spreadsheet"}

def google_sheets_tool_definitions(*, connected: bool) -> list[dict[str, Any]]:
    labels = {"google_sheets_list_spreadsheets":"[Google Sheets] Listar planilhas","google_sheets_read_sheet":"[Google Sheets] Ler planilha","google_sheets_append_row":"[Google Sheets] Adicionar linha","google_sheets_update_row":"[Google Sheets] Atualizar linha","google_sheets_create_spreadsheet":"[Google Sheets] Criar planilha"}
    desc = {"google_sheets_list_spreadsheets":"Lista planilhas do Google Sheets conectado, mostrando nome e data, sem expor IDs internos por padrão.","google_sheets_read_sheet":"Lê linhas de uma planilha do Google Sheets conectado e retorna resumo.","google_sheets_append_row":"Adiciona uma linha em planilha do Google Sheets após confirmação.","google_sheets_update_row":"Atualiza uma linha em planilha do Google Sheets após confirmação.","google_sheets_create_spreadsheet":"Cria uma planilha no Google Sheets conectado sem confirmação adicional."}
    return [{"id": tid, "tool_id": tid, "tool_name": tid, "display_name": labels[tid], "name": labels[tid], "description": desc[tid], "input_schema": {"type":"object"}, "is_enabled": connected, "server_id": None, "server_name": "Google Sheets conectado" if connected else "Requer conexão", "metadata": {"kind":"internal", "provider": PROVIDER, "source":"google_sheets_connected", "requires_connection": not connected}} for tid in labels]

class GoogleSheetsToolAdapter:
    tool_type = "google_sheets"
    def __init__(self, db: Session | None = None, service_factory: Callable[[Session, Any], GoogleSheetsService] | None = None) -> None:
        self.db = db; self.service_factory = service_factory or (lambda db, tenant_id: GoogleSheetsService(db, tenant_id))
    def can_execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> bool:
        return tool_id in GOOGLE_SHEETS_TOOL_IDS and (self.db or (config or {}).get("db")) is not None and context.tenant_id is not None
    def execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> ToolResult:
        db = self.db or (config or {}).get("db"); args = input if isinstance(input, dict) else {}; service = self.service_factory(db, context.tenant_id)
        if tool_id == "google_sheets_list_spreadsheets": result, action = service.list_spreadsheets(**args), "list_spreadsheets"
        elif tool_id == "google_sheets_read_sheet": result, action = service.read_sheet(**args), "read_sheet"
        elif tool_id == "google_sheets_append_row": result, action = service.append_row(**args), "append_row"
        elif tool_id == "google_sheets_update_row": result, action = service.update_row(**args), "update_row"
        elif tool_id == "google_sheets_create_spreadsheet": result, action = service.create_spreadsheet(**args), "create_spreadsheet"
        else: result, action = {"ok": False, "message": "Ferramenta Google Sheets não encontrada."}, "unknown"
        ok = result.get("ok") is True
        summary = "Operação do Google Sheets concluída" if ok else str(result.get("message") or "Falha ao executar Google Sheets")
        normalized = NormalizedToolResult(ok, tool_id, type=f"google_sheets.{action}", summary=summary, data=result if ok else {}, error=None if ok else {"code": str(result.get("message") or "google_sheets_error")})
        return ToolResult(ok, self.tool_type, tool_id=tool_id, tool_name=tool_id, output=sanitize_metadata(result), structured_content={"ok": ok, "tool": tool_id, "result": sanitize_metadata(result) if ok else {}, "error": None if ok else result.get("message")}, error_code=None if ok else "google_sheets_error", metadata={"provider": PROVIDER, "source":"integration_connections"}, normalized_result=normalized)
