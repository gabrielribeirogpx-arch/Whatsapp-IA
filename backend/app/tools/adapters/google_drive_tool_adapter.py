from __future__ import annotations
from typing import Any, Callable
from sqlalchemy.orm import Session
from app.services.google_drive_service import PROVIDER, GoogleDriveService
from app.tools.base import NormalizedToolResult, ToolResult
from app.tools.context import ToolContext, sanitize_metadata

GOOGLE_DRIVE_TOOL_IDS = {"google_drive_list_files", "google_drive_search_files", "google_drive_read_file", "google_drive_create_document", "google_drive_create_folder"}

def google_drive_tool_definitions(*, connected: bool) -> list[dict[str, Any]]:
    labels = {"google_drive_list_files":"[Google Drive] Listar arquivos","google_drive_search_files":"[Google Drive] Buscar arquivos","google_drive_read_file":"[Google Drive] Ler arquivo","google_drive_create_document":"[Google Drive] Criar documento","google_drive_create_folder":"[Google Drive] Criar pasta"}
    desc = {"google_drive_list_files":"Lista arquivos do Google Drive conectado, exibindo nome, tipo e data, sem expor IDs internos por padrão.","google_drive_search_files":"Busca arquivos no Google Drive conectado.","google_drive_read_file":"Lê texto de documento/arquivo do Google Drive conectado e retorna trecho útil.","google_drive_create_document":"Cria documento no Google Docs/Drive conectado sem confirmação adicional.","google_drive_create_folder":"Cria pasta no Google Drive conectado sem confirmação adicional."}
    return [{"id": tid, "tool_id": tid, "tool_name": tid, "display_name": labels[tid], "name": labels[tid], "description": desc[tid], "input_schema": {"type":"object"}, "is_enabled": connected, "server_id": None, "server_name": "Google Drive conectado" if connected else "Requer conexão", "metadata": {"kind":"internal", "provider": PROVIDER, "source":"google_drive_connected", "requires_connection": not connected}} for tid in labels]

class GoogleDriveToolAdapter:
    tool_type = "google_drive"
    def __init__(self, db: Session | None = None, service_factory: Callable[[Session, Any], GoogleDriveService] | None = None) -> None:
        self.db = db; self.service_factory = service_factory or (lambda db, tenant_id: GoogleDriveService(db, tenant_id))
    def can_execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> bool:
        return tool_id in GOOGLE_DRIVE_TOOL_IDS and (self.db or (config or {}).get("db")) is not None and context.tenant_id is not None
    def execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> ToolResult:
        db = self.db or (config or {}).get("db"); args = input if isinstance(input, dict) else {}; service = self.service_factory(db, context.tenant_id)
        if tool_id == "google_drive_list_files": result, action = service.list_files(**args), "list_files"
        elif tool_id == "google_drive_search_files": result, action = service.search_files(**args), "search_files"
        elif tool_id == "google_drive_read_file": result, action = service.read_file(**args), "read_file"
        elif tool_id == "google_drive_create_document": result, action = service.create_document(**args), "create_document"
        elif tool_id == "google_drive_create_folder": result, action = service.create_folder(**args), "create_folder"
        else: result, action = {"ok": False, "message": "Ferramenta Google Drive não encontrada."}, "unknown"
        ok = result.get("ok") is True
        summary = "Operação do Google Drive concluída" if ok else str(result.get("message") or "Falha ao executar Google Drive")
        normalized = NormalizedToolResult(ok, tool_id, type=f"google_drive.{action}", summary=summary, data=result if ok else {}, error=None if ok else {"code": str(result.get("message") or "google_drive_error")})
        return ToolResult(ok, self.tool_type, tool_id=tool_id, tool_name=tool_id, output=sanitize_metadata(result), structured_content={"ok": ok, "tool": tool_id, "result": sanitize_metadata(result) if ok else {}, "error": None if ok else result.get("message")}, error_code=None if ok else "google_drive_error", metadata={"provider": PROVIDER, "source":"integration_connections"}, normalized_result=normalized)
