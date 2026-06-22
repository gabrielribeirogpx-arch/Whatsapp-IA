from __future__ import annotations
import hashlib
import json
import logging
from typing import Any, Callable
from sqlalchemy.orm import Session
from app.services.google_sheets_service import PROVIDER, GoogleSheetsService
from app.tools.base import NormalizedToolResult, ToolResult
from app.tools.context import ToolContext, sanitize_metadata

GOOGLE_SHEETS_TOOL_IDS = {"google_sheets_list_spreadsheets", "google_sheets_read_sheet", "google_sheets_append_row", "google_sheets_update_row", "google_sheets_create_spreadsheet"}
MUTATING_GOOGLE_SHEETS_TOOL_IDS = {"google_sheets_append_row", "google_sheets_update_row", "google_sheets_create_spreadsheet"}

logger = logging.getLogger(__name__)

def _stable_json(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    except TypeError:
        return json.dumps(str(value), ensure_ascii=False, sort_keys=True)

def _fingerprint(tool_id: str, payload: Any) -> str:
    return hashlib.sha256((str(tool_id or "").strip() + _stable_json(payload)).encode("utf-8")).hexdigest()

def google_sheets_tool_definitions(*, connected: bool) -> list[dict[str, Any]]:
    labels = {"google_sheets_list_spreadsheets":"[Google Sheets] Listar planilhas","google_sheets_read_sheet":"[Google Sheets] Ler planilha","google_sheets_append_row":"[Google Sheets] Adicionar linha","google_sheets_update_row":"[Google Sheets] Atualizar linha","google_sheets_create_spreadsheet":"[Google Sheets] Criar planilha"}
    desc = {"google_sheets_list_spreadsheets":"Lista planilhas do Google Sheets conectado, mostrando nome e data, sem expor IDs internos por padrão.","google_sheets_read_sheet":"Lê linhas de uma planilha do Google Sheets conectado e retorna resumo.","google_sheets_append_row":"Adiciona uma linha em planilha do Google Sheets após confirmação.","google_sheets_update_row":"Atualiza uma linha em planilha do Google Sheets após confirmação.","google_sheets_create_spreadsheet":"Cria uma planilha no Google Sheets conectado sem confirmação adicional."}
    return [{"id": tid, "tool_id": tid, "tool_name": tid, "display_name": labels[tid], "name": labels[tid], "description": desc[tid], "input_schema": {"type":"object"}, "is_enabled": connected, "server_id": None, "server_name": "Google Sheets conectado" if connected else "Requer conexão", "metadata": {"kind":"internal", "provider": PROVIDER, "source":"google_sheets_connected", "requires_connection": not connected}} for tid in labels]

class GoogleSheetsToolAdapter:
    tool_type = "google_sheets"
    _idempotency_results: dict[tuple[str, str], ToolResult] = {}
    def __init__(self, db: Session | None = None, service_factory: Callable[[Session, Any], GoogleSheetsService] | None = None) -> None:
        self.db = db; self.service_factory = service_factory or (lambda db, tenant_id: GoogleSheetsService(db, tenant_id))
    def can_execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> bool:
        return tool_id in GOOGLE_SHEETS_TOOL_IDS and (self.db or (config or {}).get("db")) is not None and context.tenant_id is not None
    def execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> ToolResult:
        cfg = config or {}
        db = self.db or cfg.get("db"); args = input if isinstance(input, dict) else {}; service = self.service_factory(db, context.tenant_id)
        execution_id = str((context.metadata or {}).get("execution_id") or context.trace_id or "")
        idempotency_key = (execution_id, _fingerprint(tool_id, args)) if execution_id and tool_id in MUTATING_GOOGLE_SHEETS_TOOL_IDS else None
        if idempotency_key and idempotency_key in self._idempotency_results:
            logger.info("event=AI_AGENT_DUPLICATE_TOOL_CALL_BLOCKED provider=%s tool_id=%s execution_id=%s fingerprint=%s", PROVIDER, tool_id, execution_id, idempotency_key[1])
            return self._idempotency_results[idempotency_key]
        if tool_id in {"google_sheets_append_row", "google_sheets_update_row"} and cfg.get("confirmed_pending_action") is not True:
            result, action = {"ok": False, "message": "Google Sheets append_row/update_row exigem confirmação via PendingActionService."}, "pending_action_required"
            logger.info("event=GOOGLE_SHEETS_TOOL_ERROR provider=%s tool_id=%s action=%s reason=pending_action_required", PROVIDER, tool_id, action)
        else:
            logger.info("event=GOOGLE_SHEETS_TOOL_START provider=%s tool_id=%s action=%s", PROVIDER, tool_id, tool_id.replace("google_sheets_", ""))
            if tool_id == "google_sheets_list_spreadsheets": result, action = service.list_spreadsheets(**args), "list_spreadsheets"
            elif tool_id == "google_sheets_read_sheet": result, action = service.read_sheet(**args), "read_sheet"
            elif tool_id == "google_sheets_append_row": result, action = service.append_row(**args), "append_row"
            elif tool_id == "google_sheets_update_row": result, action = service.update_row(**args), "update_row"
            elif tool_id == "google_sheets_create_spreadsheet": result, action = service.create_spreadsheet(**args), "create_spreadsheet"
            else: result, action = {"ok": False, "message": "Ferramenta Google Sheets não encontrada."}, "unknown"
        ok = result.get("ok") is True
        logger.info("event=%s provider=%s tool_id=%s action=%s", "GOOGLE_SHEETS_TOOL_SUCCESS" if ok else "GOOGLE_SHEETS_TOOL_ERROR", PROVIDER, tool_id, action)
        summary = "Operação do Google Sheets concluída" if ok else str(result.get("message") or "Falha ao executar Google Sheets")
        normalized = NormalizedToolResult(ok, tool_id, type=f"google_sheets.{action}", summary=summary, data=result if ok else {}, error=None if ok else {"code": str(result.get("message") or "google_sheets_error")})
        tool_result = ToolResult(ok, self.tool_type, tool_id=tool_id, tool_name=tool_id, output=sanitize_metadata(result), structured_content={"ok": ok, "tool": tool_id, "result": sanitize_metadata(result) if ok else {}, "error": None if ok else result.get("message")}, error_code=None if ok else "google_sheets_error", metadata={"provider": PROVIDER, "source":"integration_connections"}, normalized_result=normalized)
        if ok and idempotency_key:
            self._idempotency_results[idempotency_key] = tool_result
        return tool_result
