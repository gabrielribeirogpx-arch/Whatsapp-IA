from __future__ import annotations

import logging
import traceback

from typing import Any, Callable

from sqlalchemy.orm import Session

from app.services.google_calendar_service import PROVIDER, GoogleCalendarService
from app.tools.base import NormalizedToolResult, ToolResult
from app.tools.context import ToolContext, sanitize_metadata

logger = logging.getLogger(__name__)

GOOGLE_CALENDAR_TOOL_PREFIX = "google_calendar_"
GOOGLE_CALENDAR_TOOL_IDS = {
    "google_calendar_create_event",
    "google_calendar_list_events",
    "google_calendar_check_availability",
    "google_calendar_delete_event",
}


def google_calendar_tool_definitions(*, connected: bool) -> list[dict[str, Any]]:
    labels = {
        "google_calendar_create_event": "[Google Calendar] Criar evento",
        "google_calendar_list_events": "[Google Calendar] Listar eventos",
        "google_calendar_check_availability": "[Google Calendar] Verificar disponibilidade",
        "google_calendar_delete_event": "[Google Calendar] Excluir evento",
    }
    descriptions = {
        "google_calendar_create_event": "Cria um evento no Google Calendar conectado do workspace.",
        "google_calendar_list_events": "Lista eventos do Google Calendar conectado do workspace.",
        "google_calendar_check_availability": "Verifica disponibilidade no Google Calendar conectado do workspace.",
        "google_calendar_delete_event": "Exclui um evento do Google Calendar conectado do workspace.",
    }
    return [
        {
            "id": tool_id,
            "tool_id": tool_id,
            "tool_name": tool_id,
            "display_name": labels[tool_id],
            "name": labels[tool_id],
            "description": descriptions[tool_id],
            "input_schema": {"type": "object"},
            "is_enabled": connected,
            "server_id": None,
            "server_name": "Google Calendar conectado" if connected else "Requer conexão",
            "metadata": {"kind": "internal", "provider": "google_calendar", "source": "google_calendar_connected", "requires_connection": not connected},
        }
        for tool_id in labels
    ]


def _connection_log_context(db: Session | None, tenant_id: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"account_email": None, "calendar_id": "primary", "provider": PROVIDER, "connected": False, "status": None}
    if db is None or tenant_id is None:
        return payload
    try:
        from app.services.integration_connection_service import IntegrationConnectionService

        conn = IntegrationConnectionService(db).get_connection(tenant_id, PROVIDER)
        metadata = conn.metadata_json if conn and isinstance(conn.metadata_json, dict) else {}
        payload.update({
            "account_email": metadata.get("account_email"),
            "calendar_id": metadata.get("calendar_id") or "primary",
            "provider": conn.provider if conn else PROVIDER,
            "connected": bool(conn and conn.status == "active" and conn.auth_type == "oauth2"),
            "status": conn.status if conn else None,
        })
    except Exception as exc:
        payload.update({"exception_class": type(exc).__name__, "exception_message": str(exc), "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))})
    return payload


def _log_tool(event: str, *, tenant_id: Any, tool_name: str, input: Any, db: Session | None = None, exception: BaseException | None = None, **extra: Any) -> None:
    payload = {"tenant_id": str(tenant_id) if tenant_id is not None else None, "tool_name": tool_name, "input": input, **_connection_log_context(db, tenant_id), **extra}
    if exception is not None:
        payload.update({"exception_class": type(exception).__name__, "exception_message": str(exception), "traceback": "".join(traceback.format_exception(type(exception), exception, exception.__traceback__))})
        logger.exception("%s %s", event, sanitize_metadata(payload))
    else:
        logger.info("%s %s", event, sanitize_metadata(payload))


class GoogleCalendarToolAdapter:
    tool_type = "google_calendar"

    def __init__(self, db: Session | None = None, service_factory: Callable[[Session, Any], GoogleCalendarService] | None = None) -> None:
        self.db = db
        self.service_factory = service_factory or (lambda db, tenant_id: GoogleCalendarService(db, tenant_id))

    def can_execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> bool:
        return tool_id in GOOGLE_CALENDAR_TOOL_IDS and (self.db or (config or {}).get("db")) is not None and context.tenant_id is not None

    def execute(self, tool_id: str, input: Any, context: ToolContext, config: dict[str, Any] | None = None) -> ToolResult:
        db = self.db or (config or {}).get("db")
        args = input if isinstance(input, dict) else {}
        _log_tool("GOOGLE_CALENDAR_TOOL_START", tenant_id=context.tenant_id, tool_name=tool_id, input=input, db=db)
        _log_tool("GOOGLE_CALENDAR_TOOL_INPUT", tenant_id=context.tenant_id, tool_name=tool_id, input=args, db=db)
        connection_context = _connection_log_context(db, context.tenant_id)
        _log_tool("GOOGLE_CALENDAR_CONNECTION_FOUND" if connection_context.get("connected") else "GOOGLE_CALENDAR_CONNECTION_NOT_FOUND", tenant_id=context.tenant_id, tool_name=tool_id, input=args, db=db)
        try:
            service = self.service_factory(db, context.tenant_id)
            _log_tool("GOOGLE_CALENDAR_SERVICE_CALL", tenant_id=context.tenant_id, tool_name=tool_id, input=args, db=db)
            if tool_id == "google_calendar_create_event":
                result = service.create_event(**args)
                action = "create_event"
            elif tool_id == "google_calendar_list_events":
                result = service.list_events(**args)
                action = "list_events"
            elif tool_id == "google_calendar_check_availability":
                result = service.check_availability(**args)
                action = "check_availability"
            elif tool_id == "google_calendar_delete_event":
                result = service.delete_event(str(args.get("event_id") or args.get("id") or ""))
                action = "delete_event"
            else:
                result = {"ok": False, "message": "Ferramenta Google Calendar não encontrada."}
                action = "unknown"
        except Exception as exc:
            _log_tool("GOOGLE_CALENDAR_SERVICE_EXCEPTION", tenant_id=context.tenant_id, tool_name=tool_id, input=args, db=db, exception=exc)
            raise
        _log_tool("GOOGLE_CALENDAR_SERVICE_RESULT", tenant_id=context.tenant_id, tool_name=tool_id, input=args, db=db, result=result)
        ok = result.get("ok") is True
        summary = "Operação do Google Calendar concluída" if ok else str(result.get("message") or "Falha ao executar Google Calendar")
        normalized = NormalizedToolResult(ok, tool_id, type=f"google_calendar.{action}", summary=summary, data=result if ok else {}, error=None if ok else {"code": str(result.get("message") or "google_calendar_error")})
        tool_result = ToolResult(ok, self.tool_type, tool_id=tool_id, tool_name=tool_id, output=sanitize_metadata(result), structured_content={"ok": ok, "tool": tool_id, "result": sanitize_metadata(result) if ok else {}, "error": None if ok else result.get("message")}, error_code=None if ok else "google_calendar_error", metadata={"provider": "google_calendar", "source": "integration_connections"}, normalized_result=normalized)
        _log_tool("GOOGLE_CALENDAR_TOOL_RESULT", tenant_id=context.tenant_id, tool_name=tool_id, input=args, db=db, result=result, ok=ok, error_code=tool_result.error_code)
        return tool_result
