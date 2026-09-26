from __future__ import annotations

import logging
import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from typing import Any, Callable

from jsonschema import ValidationError, validate
from sqlalchemy.orm import Session

from app.core.appointment_metadata import (
    APPOINTMENT_METADATA_SCHEMA,
    ASA_MANAGED_KEY,
    ASA_PATIENT_REF_KEY,
    ASA_SCHEMA_KEY,
    build_appointment_private_metadata,
)
from app.core.external_identity import ExternalReferenceError
from app.services.google_calendar_service import PROVIDER, GoogleCalendarService, _connection_lookup_diagnostics
from app.tools.base import NormalizedToolResult, ToolResult
from app.tools.context import ToolContext, sanitize_metadata

logger = logging.getLogger(__name__)

GOOGLE_CALENDAR_TOOL_PREFIX = "google_calendar_"
GOOGLE_CALENDAR_TOOL_IDS = {
    "google_calendar_create_event",
    "google_calendar_update_event",
    "google_calendar_list_events",
    "google_calendar_find_managed_appointments",
    "google_calendar_check_availability",
    "google_calendar_delete_event",
    "calendar.get_availability", "calendar.create_appointment", "calendar.get_appointment",
    "calendar.reschedule_appointment", "calendar.cancel_appointment",
}

GOOGLE_CALENDAR_UPDATE_EVENT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "event_id": {
            "type": "string",
            "minLength": 1,
            "description": "Identificador do evento existente (por exemplo, {{event_to_reschedule.id}}).",
        },
        "start": {
            "type": "string",
            "format": "date-time",
            "description": "Novo início do evento em ISO 8601 (por exemplo, {{new_selected_slot.start}}).",
        },
        "end": {
            "type": "string",
            "format": "date-time",
            "description": "Novo fim do evento em ISO 8601 (por exemplo, {{new_selected_slot.end}}).",
        },
        "timezone": {
            "type": "string",
            "description": "Fuso horário IANA do novo período (por exemplo, {{new_selected_slot.timezone}}).",
        },
        "title": {"type": "string", "description": "Novo título opcional do evento."},
        "description": {"type": "string", "description": "Nova descrição opcional do evento."},
    },
    "required": ["event_id", "start", "end"],
}

GOOGLE_CALENDAR_CREATE_EVENT_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {
            "type": "string",
            "description": "Título do evento.",
        },
        "summary": {
            "type": "string",
            "description": "Título alternativo do evento, aceito pelo serviço como alias de title.",
        },
        "start": {
            "type": "string",
            "format": "date-time",
            "description": "Início do evento em ISO 8601 (por exemplo, {{selected_slot.start}}).",
        },
        "end": {
            "type": "string",
            "format": "date-time",
            "description": "Fim do evento em ISO 8601 (por exemplo, {{selected_slot.end}}).",
        },
        "timezone": {
            "type": "string",
            "description": "Fuso horário IANA do evento (por exemplo, {{selected_slot.timezone}}).",
        },
        "description": {
            "type": "string",
            "description": "Descrição opcional do evento.",
        },
        "location": {
            "type": "string",
            "description": "Local opcional do evento.",
        },
        "attendees": {
            "type": "array",
            "description": "Lista opcional de participantes, como e-mails ou objetos com o campo email.",
            "items": {
                "oneOf": [
                    {"type": "string", "format": "email"},
                    {
                        "type": "object",
                        "properties": {"email": {"type": "string", "format": "email"}},
                        "required": ["email"],
                    },
                ]
            },
        },
    },
    "required": ["start", "end"],
}

GOOGLE_CALENDAR_AVAILABILITY_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "start": {
            "type": "string",
            "format": "date-time",
            "description": "Início do período em RFC3339/ISO 8601 (por exemplo, {{appointment_period.window_start}}).",
        },
        "end": {
            "type": "string",
            "format": "date-time",
            "description": "Fim do período em RFC3339/ISO 8601 (por exemplo, {{appointment_period.window_end}}).",
        },
        "timezone": {
            "type": "string",
            "description": "Fuso horário IANA (por exemplo, {{appointment_period.timezone}}).",
        },
        "mode": {
            "type": "string",
            "enum": ["period", "exact"],
            "description": "Modo de cálculo da disponibilidade (por exemplo, period).",
        },
    },
    "required": ["start", "end"],
}

GOOGLE_CALENDAR_FIND_MANAGED_APPOINTMENTS_INPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "start": {"type": "string", "format": "date-time"},
        "end": {"type": "string", "format": "date-time"},
        "timezone": {"type": "string", "minLength": 1},
    },
    "required": ["start", "end"],
    "additionalProperties": False,
}

MANAGED_APPOINTMENTS_MAX_WINDOW = timedelta(days=90)


def _calendar_failure(tool_id: str, code: str) -> ToolResult:
    normalized = NormalizedToolResult(
        False, tool_id, type="google_calendar.find_managed_appointments",
        error={"code": code},
    )
    return ToolResult(
        False, "google_calendar", tool_id=tool_id, tool_name=tool_id,
        output={"ok": False, "message": code},
        structured_content={"ok": False, "tool": tool_id, "result": {}, "error": code},
        error_code=code, error_message=code,
        metadata={"provider": "google_calendar", "source": "integration_connections"},
        normalized_result=normalized,
    )


def _parse_window_datetime(value: Any, timezone_name: str | None) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo(timezone_name or "America/Sao_Paulo"))
        return parsed
    except (ValueError, TypeError, ZoneInfoNotFoundError):
        return None


def _validate_managed_appointment_window(args: dict[str, Any]) -> str | None:
    timezone_name = args.get("timezone")
    if timezone_name:
        try:
            ZoneInfo(str(timezone_name))
        except ZoneInfoNotFoundError:
            return "google_calendar_invalid_timezone"
    start = _parse_window_datetime(args.get("start"), timezone_name)
    if start is None:
        return "google_calendar_invalid_start"
    end = _parse_window_datetime(args.get("end"), timezone_name)
    if end is None:
        return "google_calendar_invalid_end"
    if end <= start:
        return "google_calendar_invalid_time_range"
    if end - start > MANAGED_APPOINTMENTS_MAX_WINDOW:
        return "google_calendar_time_range_too_large"
    return None


def _managed_appointment_dtos(
    events: Any, patient_ref: str, fallback_timezone: str
) -> list[dict[str, str]]:
    appointments: list[dict[str, str]] = []
    for event in events if isinstance(events, list) else []:
        if not isinstance(event, dict) or event.get("status") == "cancelled":
            continue
        private = ((event.get("extendedProperties") or {}).get("private") or {})
        if not isinstance(private, dict) or (
            private.get(ASA_MANAGED_KEY) != "true"
            or private.get(ASA_SCHEMA_KEY) != APPOINTMENT_METADATA_SCHEMA
            or private.get(ASA_PATIENT_REF_KEY) != patient_ref
        ):
            continue
        start_data = event.get("start") if isinstance(event.get("start"), dict) else {}
        end_data = event.get("end") if isinstance(event.get("end"), dict) else {}
        start = start_data.get("dateTime") or start_data.get("date")
        end = end_data.get("dateTime") or end_data.get("date")
        event_id = event.get("id")
        if not event_id or not start or not end:
            continue
        timezone_name = str(start_data.get("timeZone") or end_data.get("timeZone") or fallback_timezone)
        parsed_start = _parse_window_datetime(start, timezone_name)
        if parsed_start is None:
            continue
        try:
            local_start = parsed_start.astimezone(ZoneInfo(timezone_name))
        except ZoneInfoNotFoundError:
            timezone_name = fallback_timezone
            local_start = parsed_start.astimezone(ZoneInfo(fallback_timezone))
        appointments.append({
            "id": str(event_id),
            "label": local_start.strftime("%d/%m às %H:%M"),
            "start": str(start),
            "end": str(end),
            "timezone": timezone_name,
        })
    appointments.sort(key=lambda item: (
        _parse_window_datetime(item["start"], item["timezone"]).timestamp(), item["id"]
    ))
    return appointments


def google_calendar_tool_definitions(*, connected: bool) -> list[dict[str, Any]]:
    labels = {
        "google_calendar_create_event": "[Google Calendar] Criar evento",
        "google_calendar_update_event": "[Google Calendar] Atualizar evento",
        "google_calendar_list_events": "[Google Calendar] Listar eventos",
        "google_calendar_find_managed_appointments": "[Google Calendar] Localizar agendamentos gerenciados",
        "google_calendar_check_availability": "[Google Calendar] Verificar disponibilidade",
        "google_calendar_delete_event": "[Google Calendar] Excluir evento",
    }
    descriptions = {
        "google_calendar_create_event": "Cria um evento no Google Calendar conectado do workspace.",
        "google_calendar_update_event": "Atualiza um evento existente no Google Calendar conectado do workspace.",
        "google_calendar_list_events": "Lista eventos do Google Calendar conectado do workspace.",
        "google_calendar_find_managed_appointments": "Localiza agendamentos Asa do contato atual em uma janela de até 90 dias.",
        "google_calendar_check_availability": "Verifica disponibilidade no Google Calendar conectado do workspace.",
        "google_calendar_delete_event": "Exclui um evento do Google Calendar conectado do workspace.",
    }
    labels.update({
        "calendar.get_availability": "Consultar disponibilidade",
        "calendar.create_appointment": "Criar compromisso",
        "calendar.get_appointment": "Consultar compromisso",
        "calendar.reschedule_appointment": "Reagendar compromisso",
        "calendar.cancel_appointment": "Cancelar compromisso",
    })
    descriptions.update({
        "calendar.get_availability": "Consulta horários livres dentro de um período.",
        "calendar.create_appointment": "Cria um evento após confirmação.",
        "calendar.get_appointment": "Consulta um compromisso pelo identificador.",
        "calendar.reschedule_appointment": "Altera a data ou horário de um compromisso após confirmação.",
        "calendar.cancel_appointment": "Cancela um compromisso após confirmação.",
    })
    classifications = {"calendar.create_appointment": "WRITE", "calendar.reschedule_appointment": "WRITE", "calendar.cancel_appointment": "DESTRUCTIVE", "google_calendar_create_event": "WRITE", "google_calendar_update_event": "WRITE", "google_calendar_delete_event": "DESTRUCTIVE"}
    return [
        {
            "id": tool_id,
            "tool_id": tool_id,
            "tool_name": tool_id,
            "display_name": labels[tool_id],
            "name": labels[tool_id],
            "description": descriptions[tool_id],
            "input_schema": (
                GOOGLE_CALENDAR_CREATE_EVENT_INPUT_SCHEMA
                if tool_id == "google_calendar_create_event"
                else GOOGLE_CALENDAR_UPDATE_EVENT_INPUT_SCHEMA
                if tool_id == "google_calendar_update_event"
                else GOOGLE_CALENDAR_AVAILABILITY_INPUT_SCHEMA
                if tool_id in {"google_calendar_check_availability", "calendar.get_availability"}
                else GOOGLE_CALENDAR_FIND_MANAGED_APPOINTMENTS_INPUT_SCHEMA
                if tool_id == "google_calendar_find_managed_appointments"
                else {"type": "object"}
            ),
            "is_enabled": connected,
            "server_id": None,
            "server_name": "Google Calendar conectado" if connected else "Requer conexão",
            "metadata": {"kind": "internal", "provider": "google_calendar", "source": "google_calendar_connected", "requires_connection": not connected, "classification": classifications.get(tool_id, "READ")},
        }
        for tool_id in labels
    ]



def _calendar_create_start_context(args: dict[str, Any]) -> dict[str, Any]:
    return {
        "connection_id": None,
        "calendar_id": "primary",
        "title": args.get("title") or args.get("summary") or args.get("name"),
        "start_time": args.get("start_time") or args.get("start") or args.get("time_min") or args.get("timeMin"),
        "end_time": args.get("end_time") or args.get("end") or args.get("time_max") or args.get("timeMax"),
    }


def _calendar_event_result_data(result: dict[str, Any]) -> dict[str, Any]:
    event = result.get("result") if isinstance(result.get("result"), dict) else result
    start = event.get("start")
    end = event.get("end")
    if isinstance(start, dict):
        start = start.get("dateTime") or start.get("date")
    if isinstance(end, dict):
        end = end.get("dateTime") or end.get("date")
    return {
        "event_id": event.get("event_id") or event.get("id"),
        "event_link": event.get("event_link") or event.get("html_link") or event.get("htmlLink"),
        "title": event.get("title") or event.get("summary") or event.get("name"),
        "start": start or event.get("start_time"),
        "end": end or event.get("end_time"),
    }


def _calendar_error_data(result: dict[str, Any], tool_result: ToolResult | None = None) -> dict[str, Any]:
    message = result.get("message") or result.get("error") or result.get("api_error")
    if isinstance(message, dict):
        message = message.get("message") or message.get("error") or str(message)
    error_type = result.get("error_type") or result.get("code") or result.get("status_code") or (tool_result.error_code if tool_result else None) or "google_calendar_error"
    return {"error_type": str(error_type), "error_message": str(message or error_type)}

def _connection_log_context(db: Session | None, tenant_id: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"connection_id": None, "connection_tenant_id": None, "account_email": None, "calendar_id": "primary", "provider": PROVIDER, "connected": False, "status": None, "access_token_encrypted_is_not_null": False, "refresh_token_encrypted_is_not_null": False, "access_token_present": False, "refresh_token_present": False}
    if db is None or tenant_id is None:
        return payload
    try:
        from app.services.integration_connection_service import IntegrationConnectionService

        payload.update(_connection_lookup_diagnostics(tenant_id, PROVIDER, active_only=True))
        conn = IntegrationConnectionService(db).get_active_connection(tenant_id, PROVIDER)
        metadata = conn.metadata_json if conn and isinstance(conn.metadata_json, dict) else {}
        payload.update({
            "connection_id": str(conn.id) if conn else None,
            "connection_tenant_id": str(conn.tenant_id) if conn else None,
            "account_email": metadata.get("account_email"),
            "calendar_id": metadata.get("calendar_id") or "primary",
            "provider": conn.provider if conn else PROVIDER,
            "connected": bool(conn and conn.status == "active" and conn.auth_type == "oauth2"),
            "status": conn.status if conn else None,
            "access_token_encrypted_is_not_null": bool(conn and conn.access_token_encrypted is not None),
            "refresh_token_encrypted_is_not_null": bool(conn and conn.refresh_token_encrypted is not None),
            "access_token_present": bool(conn and conn.access_token_encrypted),
            "refresh_token_present": bool(conn and conn.refresh_token_encrypted),
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
        validation_schema = (
            GOOGLE_CALENDAR_CREATE_EVENT_INPUT_SCHEMA
            if tool_id == "google_calendar_create_event"
            else GOOGLE_CALENDAR_UPDATE_EVENT_INPUT_SCHEMA
            if tool_id == "google_calendar_update_event"
            else GOOGLE_CALENDAR_FIND_MANAGED_APPOINTMENTS_INPUT_SCHEMA
            if tool_id == "google_calendar_find_managed_appointments"
            else None
        )
        if validation_schema is not None:
            try:
                validate(instance=args, schema=validation_schema)
            except ValidationError:
                message = "google_calendar_invalid_arguments"
                action = (
                    "find_managed_appointments"
                    if tool_id == "google_calendar_find_managed_appointments"
                    else "update_event" if tool_id == "google_calendar_update_event" else "create_event"
                )
                normalized = NormalizedToolResult(False, tool_id, type=f"google_calendar.{action}", error={"code": message})
                return ToolResult(
                    False,
                    self.tool_type,
                    tool_id=tool_id,
                    tool_name=tool_id,
                    output={"ok": False, "message": message},
                    structured_content={"ok": False, "tool": tool_id, "result": {}, "error": message},
                    error_code=message,
                    metadata={"provider": "google_calendar", "source": "integration_connections"},
                    normalized_result=normalized,
                )
        appointment_metadata: dict[str, str] | None = None
        if tool_id == "google_calendar_find_managed_appointments":
            validation_error = _validate_managed_appointment_window(args)
            if validation_error:
                return _calendar_failure(tool_id, validation_error)
            if context.contact_id is None:
                return _calendar_failure(tool_id, "google_calendar_contact_identity_required")
            try:
                appointment_metadata = build_appointment_private_metadata(
                    tenant_id=context.tenant_id, contact_id=context.contact_id
                )
            except ExternalReferenceError:
                return _calendar_failure(tool_id, "google_calendar_external_identity_unavailable")
        if tool_id == "google_calendar_create_event" and context.contact_id is not None:
            try:
                appointment_metadata = build_appointment_private_metadata(
                    tenant_id=context.tenant_id,
                    contact_id=context.contact_id,
                )
            except ExternalReferenceError as exc:
                message = "google_calendar_external_identity_unavailable"
                normalized = NormalizedToolResult(
                    False,
                    tool_id,
                    type="google_calendar.create_event",
                    error={"code": message},
                )
                _log_tool(
                    "GOOGLE_CALENDAR_EXTERNAL_IDENTITY_FAILED",
                    tenant_id=context.tenant_id,
                    tool_name=tool_id,
                    input=args,
                    db=db,
                    exception=exc,
                )
                return ToolResult(
                    False,
                    self.tool_type,
                    tool_id=tool_id,
                    tool_name=tool_id,
                    output={"ok": False, "message": message},
                    structured_content={"ok": False, "tool": tool_id, "result": {}, "error": message},
                    error_code=message,
                    error_message=message,
                    metadata={"provider": "google_calendar", "source": "integration_connections"},
                    normalized_result=normalized,
                )
        try:
            service = self.service_factory(db, context.tenant_id)
            _log_tool("GOOGLE_CALENDAR_ADAPTER_PAYLOAD", tenant_id=context.tenant_id, tool_name=tool_id, input=args, db=db, payload=args)
            _log_tool("GOOGLE_CALENDAR_SERVICE_PAYLOAD", tenant_id=context.tenant_id, tool_name=tool_id, input=args, db=db, payload=args)
            _log_tool("GOOGLE_CALENDAR_SERVICE_CALL", tenant_id=context.tenant_id, tool_name=tool_id, input=args, db=db)
            if tool_id in {"google_calendar_create_event", "calendar.create_appointment"}:
                create_context = {**_calendar_create_start_context(args), **connection_context}
                _log_tool("AI_AGENT_CALENDAR_CREATE_START", tenant_id=context.tenant_id, tool_name=tool_id, input=args, db=db, **create_context)
                _log_tool("GOOGLE_CALENDAR_CREATE_EVENT_INPUT", tenant_id=context.tenant_id, tool_name=tool_id, input=args, db=db, **create_context)
                # This explicit parameter is derived from trusted ToolContext and
                # cannot be supplied or overridden by rendered flow arguments.
                if appointment_metadata is None:
                    # LEGACY UNMANAGED EVENT: preserve the historical call when
                    # no trusted patient identity is available.
                    result = service.create_event(**args)
                else:
                    result = service.create_event(
                        **{key: value for key, value in args.items() if key != "asa_private_metadata"},
                        asa_private_metadata=appointment_metadata,
                    )
                action = "create_event"
            elif tool_id == "google_calendar_find_managed_appointments":
                result = service.find_managed_appointments(
                    start=args["start"],
                    end=args["end"],
                    timezone=args.get("timezone"),
                    patient_ref=appointment_metadata[ASA_PATIENT_REF_KEY],
                    metadata_schema=APPOINTMENT_METADATA_SCHEMA,
                )
                action = "find_managed_appointments"
            elif tool_id in {"google_calendar_list_events", "calendar.get_appointment"}:
                result = service.list_events(**args)
                action = "list_events"
            elif tool_id in {"google_calendar_check_availability", "calendar.get_availability"}:
                result = service.check_availability(**args)
                action = "check_availability"
            elif tool_id in {"google_calendar_delete_event", "calendar.cancel_appointment"}:
                result = service.delete_event(str(args.get("event_id") or args.get("id") or ""))
                action = "delete_event"
            elif tool_id in {"google_calendar_update_event", "calendar.reschedule_appointment"}:
                event_id = str(args.get("event_id") or args.get("id") or "")
                result = service.update_event(event_id, **{key: value for key, value in args.items() if key not in {"event_id", "id"}})
                action = "update_event"
            else:
                result = {"ok": False, "message": "Ferramenta Google Calendar não encontrada."}
                action = "unknown"
        except Exception as exc:
            _log_tool("GOOGLE_CALENDAR_SERVICE_EXCEPTION", tenant_id=context.tenant_id, tool_name=tool_id, input=args, db=db, exception=exc)
            if tool_id == "google_calendar_find_managed_appointments":
                return _calendar_failure(tool_id, "google_calendar_api_error")
            raise
        _log_tool("GOOGLE_CALENDAR_SERVICE_RESULT", tenant_id=context.tenant_id, tool_name=tool_id, input=args, db=db, result=result)
        if tool_id == "google_calendar_find_managed_appointments" and result.get("ok") is not True:
            message = str(result.get("message") or "")
            code = (
                "google_calendar_integration_unavailable"
                if "não está conectado" in message
                else "google_calendar_api_error"
            )
            return _calendar_failure(tool_id, code)
        if tool_id == "google_calendar_create_event":
            _log_tool("AI_AGENT_CALENDAR_CREATE_RAW_RESULT", tenant_id=context.tenant_id, tool_name=tool_id, input=args, db=db, raw_response=result)
        ok = result.get("ok") is True
        if tool_id == "google_calendar_find_managed_appointments" and ok:
            appointments = _managed_appointment_dtos(
                result.get("events"), appointment_metadata[ASA_PATIENT_REF_KEY],
                str(result.get("timezone") or args.get("timezone") or "America/Sao_Paulo"),
            )
            normalized = NormalizedToolResult(
                True, tool_id, type="google_calendar.find_managed_appointments",
                summary="Agendamentos gerenciados localizados", data={"appointments": appointments},
            )
            return ToolResult(
                True, self.tool_type, tool_id=tool_id, tool_name=tool_id,
                output=appointments,
                structured_content={"ok": True, "tool": tool_id, "result": appointments, "error": None},
                metadata={"provider": "google_calendar", "source": "integration_connections"},
                normalized_result=normalized,
            )
        event_data = _calendar_event_result_data(result) if tool_id == "google_calendar_create_event" else {}
        create_ok = ok and bool(event_data.get("event_id")) if tool_id == "google_calendar_create_event" else ok
        if tool_id == "google_calendar_create_event" and ok and not event_data.get("event_id"):
            result = {**result, "ok": False, "message": "google_calendar_missing_event_id", "original_ok": True}
            ok = False
        summary = "Operação do Google Calendar concluída" if ok else str(result.get("message") or "Falha ao executar Google Calendar")
        normalized = NormalizedToolResult(ok, tool_id, type=f"google_calendar.{action}", summary=summary, data=result if ok else {}, error=None if ok else {"code": str(result.get("message") or "google_calendar_error")})
        tool_result = ToolResult(ok, self.tool_type, tool_id=tool_id, tool_name=tool_id, output=sanitize_metadata(result), structured_content={"ok": ok, "tool": tool_id, "result": sanitize_metadata(result) if ok else {}, "error": None if ok else result.get("message")}, error_code=None if ok else "google_calendar_error", metadata={"provider": "google_calendar", "source": "integration_connections"}, normalized_result=normalized)
        if tool_id == "google_calendar_create_event":
            normalized_payload = {"ok": create_ok, "error": None if create_ok else _calendar_error_data(result, tool_result), "event_id": event_data.get("event_id"), "event_link": event_data.get("event_link")}
            _log_tool("AI_AGENT_CALENDAR_CREATE_NORMALIZED", tenant_id=context.tenant_id, tool_name=tool_id, input=args, db=db, **normalized_payload)
            if create_ok:
                _log_tool("GOOGLE_CALENDAR_EVENT_CREATED", tenant_id=context.tenant_id, tool_name=tool_id, input=args, db=db, event_id=event_data.get("event_id"), title=event_data.get("title"), start=event_data.get("start"), end=event_data.get("end"))
            else:
                _log_tool("GOOGLE_CALENDAR_EVENT_FAILED", tenant_id=context.tenant_id, tool_name=tool_id, input=args, db=db, **_calendar_error_data(result, tool_result))
        _log_tool("GOOGLE_CALENDAR_TOOL_RESULT", tenant_id=context.tenant_id, tool_name=tool_id, input=args, db=db, result=result, ok=ok, error_code=tool_result.error_code)
        return tool_result
