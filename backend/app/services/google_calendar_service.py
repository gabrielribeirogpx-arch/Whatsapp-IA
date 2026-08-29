from __future__ import annotations

import logging
import os
import re
import traceback
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.integration_connection import IntegrationConnection
from app.services.integration_connection_service import GOOGLE_RECONNECT_MESSAGE, IntegrationConnectionService, is_google_auth_error
from app.tools.context import sanitize_metadata

logger = logging.getLogger(__name__)

PROVIDER = "google_calendar"
BASE_URL = "https://www.googleapis.com/calendar/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
NOT_CONNECTED_MESSAGE = "Google Calendar não está conectado para este workspace."
DEFAULT_TIMEZONE = "America/Sao_Paulo"

class GoogleCalendarTokenDecryptError(RuntimeError):
    """Raised when an encrypted Google Calendar credential cannot be decrypted."""


def _now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _connection_lookup_diagnostics(tenant_id: uuid.UUID | str, provider: str = PROVIDER, *, active_only: bool = False) -> dict[str, Any]:
    statement = select(IntegrationConnection).where(
        IntegrationConnection.tenant_id == tenant_id,
        IntegrationConnection.provider == provider,
    )
    filters: dict[str, Any] = {"tenant_id": str(tenant_id), "provider": provider}
    if active_only:
        statement = statement.where(IntegrationConnection.status == "active").order_by(IntegrationConnection.updated_at.desc()).limit(1)
        filters["status"] = "active"
        filters["order_by"] = "updated_at desc"
        filters["limit"] = 1
    try:
        compiled = statement.compile(compile_kwargs={"literal_binds": False})
        sql = str(compiled)
        params = {key: str(value) for key, value in compiled.params.items()}
    except Exception as exc:
        sql = None
        params = {}
        filters["sql_compile_error"] = f"{type(exc).__name__}: {exc}"
    return {"integration_connection_sql": sql, "integration_connection_sql_params": params, "integration_connection_filters": filters}


def _connection_metadata(conn: IntegrationConnection | None) -> dict[str, Any]:
    metadata = conn.metadata_json if conn and isinstance(conn.metadata_json, dict) else {}
    return {
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
    }


class GoogleCalendarService:
    def __init__(self, db: Session, tenant_id: uuid.UUID | str):
        self.db = db
        self.tenant_id = uuid.UUID(str(tenant_id))
        self.connection_service = IntegrationConnectionService(db)

    def _log(self, event: str, *, tool_name: str | None = None, input: Any = None, conn: IntegrationConnection | None = None, calendar_id: str | None = None, exception: BaseException | None = None, **extra: Any) -> None:
        payload = {
            "event": event,
            "tenant_id": str(self.tenant_id),
            "tool_name": tool_name,
            "input": input,
            **_connection_metadata(conn),
            **extra,
        }
        if calendar_id:
            payload["calendar_id"] = calendar_id
        if exception is not None:
            payload.update({
                "exception_class": type(exception).__name__,
                "exception_message": str(exception),
                "traceback": "".join(traceback.format_exception(type(exception), exception, exception.__traceback__)),
            })
            logger.exception("%s %s", event, sanitize_metadata(payload))
        else:
            logger.info("%s %s", event, sanitize_metadata(payload))

    def _connection(self, *, tool_name: str | None = None, input: Any = None) -> IntegrationConnection | None:
        self._log("GOOGLE_CALENDAR_INTEGRATION_CONNECTION_QUERY", tool_name=tool_name, input=input, **_connection_lookup_diagnostics(self.tenant_id, PROVIDER, active_only=True))
        conn = self.connection_service.get_active_connection(self.tenant_id, PROVIDER)
        if not conn or conn.auth_type != "oauth2":
            self._log("GOOGLE_CALENDAR_CONNECTION_NOT_FOUND", tool_name=tool_name, input=input, conn=conn)
            return None
        self._log("GOOGLE_CALENDAR_CONNECTION_FOUND", tool_name=tool_name, input=input, conn=conn)
        self._log(
            "GOOGLE_CALENDAR_CONNECTION_ROW",
            tool_name=tool_name,
            input=input,
            conn=conn,
            access_token_encrypted_len=len(conn.access_token_encrypted or "") if conn.access_token_encrypted is not None else 0,
            refresh_token_encrypted_len=len(conn.refresh_token_encrypted or "") if conn.refresh_token_encrypted is not None else 0,
            expires_at=conn.expires_at.isoformat() if conn.expires_at else None,
        )
        return conn

    def _decrypt_token(self, conn: IntegrationConnection, field_name: str, encrypted_value: str | None) -> str | None:
        event_payload = {"token_field": field_name, "encrypted_value_is_not_null": encrypted_value is not None}
        if field_name == "refresh_token_encrypted":
            self._log("GOOGLE_CALENDAR_REFRESH_TOKEN_DECRYPT_START", conn=conn, **event_payload)
        self._log(f"GOOGLE_CALENDAR_DECRYPT_{field_name.upper()}_START", conn=conn, **event_payload)
        try:
            decrypted = IntegrationConnectionService.decrypt_credential_strict(encrypted_value)
        except Exception as exc:
            if field_name == "refresh_token_encrypted":
                self._log("GOOGLE_CALENDAR_REFRESH_TOKEN_DECRYPT_FAILED", conn=conn, exception=exc, **event_payload)
                raise GoogleCalendarTokenDecryptError("google_calendar_token_decrypt_failed") from exc
            self._log(f"GOOGLE_CALENDAR_DECRYPT_{field_name.upper()}_EXCEPTION", conn=conn, exception=exc, **event_payload)
            raise
        if field_name == "refresh_token_encrypted":
            self._log("GOOGLE_CALENDAR_REFRESH_TOKEN_DECRYPT_SUCCESS", conn=conn, decrypted_value_loaded=bool(decrypted), **event_payload)
        self._log(f"GOOGLE_CALENDAR_DECRYPT_{field_name.upper()}_END", conn=conn, decrypted_value_loaded=bool(decrypted), **event_payload)
        return decrypted

    def _tokens(self, conn: IntegrationConnection) -> tuple[str | None, str | None]:
        access = self._decrypt_token(conn, "access_token_encrypted", conn.access_token_encrypted)
        refresh = self._decrypt_token(conn, "refresh_token_encrypted", conn.refresh_token_encrypted)
        self._log("GOOGLE_CALENDAR_TOKEN_DECRYPT_RESULT", conn=conn, access_token_loaded=bool(access), refresh_token_loaded=bool(refresh))
        return access, refresh

    def _tenant_timezone(self, explicit: str | None = None) -> str:
        candidates = [explicit]
        conn = self.connection_service.get_connection(self.tenant_id, PROVIDER)
        metadata = conn.metadata_json if conn and isinstance(conn.metadata_json, dict) else {}
        candidates += [metadata.get("timezone"), metadata.get("time_zone")]
        for item in candidates:
            if item:
                try:
                    ZoneInfo(str(item))
                    return str(item)
                except ZoneInfoNotFoundError:
                    continue
        return DEFAULT_TIMEZONE

    def _normalize_datetime(self, value: Any, tz_name: str) -> str | None:
        if value in (None, ""):
            return None
        if isinstance(value, datetime):
            dt = value
        else:
            text = str(value).strip()
            if re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
                text += "T00:00:00"
            elif re.fullmatch(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}", text):
                text += ":00"
            text = text.replace("Z", "+00:00")
            try:
                dt = datetime.fromisoformat(text)
            except ValueError:
                return str(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(tz_name))
        return dt.isoformat()

    def _event_payload(self, data: dict[str, Any]) -> dict[str, Any]:
        tz = self._tenant_timezone(data.get("timezone") or data.get("timeZone"))
        title = data.get("title") or data.get("summary") or "Evento"
        start = data.get("start") or data.get("start_time") or data.get("startTime")
        end = data.get("end") or data.get("end_time") or data.get("endTime")
        self._log("AI_AGENT_CALENDAR_CREATE_TIMEZONE", tool_name="google_calendar_create_event", input=data, timezone=tz, start=start, end=end)
        payload: dict[str, Any] = {"summary": str(title)}
        if data.get("description"):
            payload["description"] = str(data.get("description"))
        if data.get("location"):
            payload["location"] = str(data.get("location"))
        if start:
            payload["start"] = {"dateTime": self._normalize_datetime(start, tz), "timeZone": tz}
        if end:
            payload["end"] = {"dateTime": self._normalize_datetime(end, tz), "timeZone": tz}
        attendees = data.get("attendees") or []
        if isinstance(attendees, list) and attendees:
            payload["attendees"] = [{"email": str(a.get("email") if isinstance(a, dict) else a)} for a in attendees]
        return payload

    def refresh_access_token_if_needed(self, force: bool = False) -> dict[str, Any]:
        conn = self._connection(tool_name="refresh_access_token", input={"force": force})
        if not conn:
            return {"ok": False, "message": NOT_CONNECTED_MESSAGE}
        if not force and conn.expires_at and conn.expires_at > _now_utc_naive() + timedelta(seconds=60):
            return {"ok": True, "refreshed": False}
        try:
            _access, refresh = self._tokens(conn)
        except GoogleCalendarTokenDecryptError:
            return {"ok": False, "message": "google_calendar_token_decrypt_failed"}
        if conn.refresh_token_encrypted and not refresh:
            return {"ok": False, "message": "google_calendar_refresh_token_empty_after_decrypt"}
        if not refresh:
            return {"ok": False, "message": "Refresh token do Google Calendar não está disponível."}
        client_id = (
            os.getenv("GOOGLE_CALENDAR_CLIENT_ID")
            or os.getenv("GOOGLE_CLIENT_ID")
            or os.getenv("GOOGLE_OAUTH_CLIENT_ID")
            or ""
        ).strip()
        client_secret = (
            os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET")
            or os.getenv("GOOGLE_CLIENT_SECRET")
            or os.getenv("GOOGLE_OAUTH_CLIENT_SECRET")
            or ""
        ).strip()
        grant_type = "refresh_token"
        self._log(
            "GOOGLE_CALENDAR_TOKEN_REFRESH_REQUEST",
            conn=conn,
            client_id_present=bool(client_id),
            client_secret_present=bool(client_secret),
            refresh_token_present=bool(refresh),
            token_url=TOKEN_URL,
            grant_type=grant_type,
        )
        try:
            resp = requests.post(TOKEN_URL, data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh,
                "grant_type": grant_type,
            }, timeout=15)
            if resp.status_code >= 400:
                response_text = getattr(resp, "text", None)
                response_json = None
                if response_text is None:
                    response_text = ""
                try:
                    response_json = resp.json()
                except Exception:
                    response_json = None
                error = response_json.get("error") if isinstance(response_json, dict) else None
                error_description = response_json.get("error_description") if isinstance(response_json, dict) else None
                self._log(
                    "GOOGLE_CALENDAR_TOKEN_REFRESH_FAILED",
                    conn=conn,
                    status_code=resp.status_code,
                    response_text=response_text,
                    response_json=response_json,
                    error=error,
                    error_description=error_description,
                )
                if is_google_auth_error(resp.status_code, response_json, error):
                    self.connection_service.mark_google_connection_revoked(self.tenant_id, PROVIDER)
                    return {"ok": False, "message": "google_calendar_refresh_invalid_grant", "user_message": GOOGLE_RECONNECT_MESSAGE, "status_code": resp.status_code, "api_error": response_json}
                if error == "invalid_client":
                    return {"ok": False, "message": "google_calendar_refresh_invalid_client", "user_message": "Credenciais OAuth do Google Calendar inválidas. Verifique GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET."}
                if error == "redirect_uri_mismatch":
                    return {"ok": False, "message": "google_calendar_refresh_redirect_uri_mismatch"}
                return {"ok": False, "message": "google_calendar_refresh_failed"}
            data = resp.json()
            access = data.get("access_token")
            if not access:
                return {"ok": False, "message": "Resposta de renovação do Google Calendar sem access_token."}
            expires_at = _now_utc_naive() + timedelta(seconds=int(data.get("expires_in") or 3600))
            self.connection_service.update_tokens(tenant_id=self.tenant_id, provider=PROVIDER, access_token=access, expires_at=expires_at)
            return {"ok": True, "refreshed": True}
        except requests.RequestException as exc:
            self._log("GOOGLE_CALENDAR_SERVICE_EXCEPTION", tool_name="refresh_access_token", input={"force": force}, conn=conn, exception=exc)
            raise

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None, retry: bool = True, auth_trace: dict[str, Any] | None = None) -> tuple[bool, Any, int]:
        if auth_trace is not None:
            auth_trace.setdefault("access_token_present", False)
            auth_trace.setdefault("refresh_token_present", False)
            auth_trace.setdefault("refresh_attempted", False)
            auth_trace.setdefault("refresh_success", False)
            auth_trace.setdefault("refresh_failed_reason", None)
        conn = self._connection(tool_name=f"{method} {path}", input={"params": params, "json_body": json_body})
        if not conn:
            if auth_trace is not None:
                auth_trace["refresh_failed_reason"] = NOT_CONNECTED_MESSAGE
            return False, {"message": NOT_CONNECTED_MESSAGE}, 0
        if conn.expires_at and conn.expires_at <= _now_utc_naive() + timedelta(seconds=60):
            if auth_trace is not None:
                auth_trace["refresh_attempted"] = True
            refreshed = self.refresh_access_token_if_needed(force=True)
            if refreshed.get("ok") is False:
                if auth_trace is not None:
                    auth_trace["refresh_failed_reason"] = refreshed.get("message")
                return False, refreshed, 0
            if auth_trace is not None:
                auth_trace["refresh_success"] = bool(refreshed.get("refreshed"))
            conn = self._connection(tool_name=f"{method} {path}", input={"params": params, "json_body": json_body})
        try:
            access, refresh = self._tokens(conn)
        except GoogleCalendarTokenDecryptError:
            if auth_trace is not None:
                auth_trace["refresh_failed_reason"] = "google_calendar_token_decrypt_failed"
            return False, {"message": "google_calendar_token_decrypt_failed"}, 0
        if auth_trace is not None:
            auth_trace["access_token_present"] = bool(access)
            auth_trace["refresh_token_present"] = bool(refresh)
        if conn.refresh_token_encrypted and not refresh:
            if auth_trace is not None:
                auth_trace["refresh_failed_reason"] = "google_calendar_refresh_token_empty_after_decrypt"
            return False, {"message": "google_calendar_refresh_token_empty_after_decrypt"}, 0
        self._log("GOOGLE_CALENDAR_TOKEN_PRESENCE", tool_name=f"{method} {path}", input={"params": params, "json_body": json_body}, conn=conn, access_token_present=bool(access), refresh_token_present=bool(refresh))
        if not access:
            if auth_trace is not None:
                auth_trace["refresh_failed_reason"] = "missing_access_token"
            self._log("GOOGLE_CALENDAR_REQUEST_BLOCKED", tool_name=f"{method} {path}", input={"params": params, "json_body": json_body}, conn=conn, reason="missing_access_token")
            return False, {"message": NOT_CONNECTED_MESSAGE}, 0
        calendar_id = "primary"
        if path.startswith("/calendars/"):
            calendar_id = path.split("/", 3)[2]
        request_input = {"method": method, "path": path, "params": params, "json_body": json_body}
        self._log("GOOGLE_CALENDAR_API_REQUEST", tool_name=f"{method} {path}", input=request_input, conn=conn, calendar_id=calendar_id, method=method, path=path, url=f"{BASE_URL}{path}", has_json_body=json_body is not None, has_params=params is not None)
        try:
            resp = requests.request(method, f"{BASE_URL}{path}", headers={"Authorization": f"Bearer {access}", "Accept": "application/json"}, params=params, json=json_body, timeout=15)
        except Exception as exc:
            self._log("GOOGLE_CALENDAR_SERVICE_EXCEPTION", tool_name=f"{method} {path}", input=request_input, conn=conn, calendar_id=calendar_id, exception=exc)
            raise
        self._log("GOOGLE_CALENDAR_API_HTTP_STATUS", tool_name=f"{method} {path}", input=request_input, conn=conn, calendar_id=calendar_id, status_code=resp.status_code)
        if resp.status_code == 401 and retry:
            if auth_trace is not None:
                auth_trace["refresh_attempted"] = True
            refreshed = self.refresh_access_token_if_needed(force=True)
            if refreshed.get("ok"):
                if auth_trace is not None:
                    auth_trace["refresh_success"] = bool(refreshed.get("refreshed"))
                return self._request(method, path, params=params, json_body=json_body, retry=False, auth_trace=auth_trace)
            if auth_trace is not None:
                auth_trace["refresh_failed_reason"] = refreshed.get("message")
            return False, refreshed, resp.status_code
        response_payload = {"status_code": resp.status_code, "path": path}
        if resp.status_code >= 400:
            try:
                response_payload["body"] = resp.json()
            except Exception:
                response_payload["body"] = getattr(resp, "text", None)
            self._log("GOOGLE_CALENDAR_API_ERROR", tool_name=f"{method} {path}", input=request_input, conn=conn, calendar_id=calendar_id, **response_payload)
            if is_google_auth_error(resp.status_code, response_payload.get("body")):
                self.connection_service.mark_google_connection_revoked(self.tenant_id, PROVIDER)
                return False, {"message": GOOGLE_RECONNECT_MESSAGE, "status_code": resp.status_code, "api_error": response_payload.get("body")}, resp.status_code
            return False, {"message": "Erro ao chamar Google Calendar.", "status_code": resp.status_code, "api_error": response_payload.get("body")}, resp.status_code
        try:
            data = {} if resp.status_code == 204 or not resp.content else resp.json()
        except Exception as exc:
            self._log("GOOGLE_CALENDAR_SERVICE_EXCEPTION", tool_name=f"{method} {path}", input=request_input, conn=conn, calendar_id=calendar_id, exception=exc, status_code=resp.status_code)
            raise
        self._log("GOOGLE_CALENDAR_API_RESPONSE", tool_name=f"{method} {path}", input=request_input, conn=conn, calendar_id=calendar_id, status_code=resp.status_code, response=data)
        return True, data, resp.status_code

    def _service_call(self, tool_name: str, input: dict[str, Any], operation: Callable[[], dict[str, Any]]) -> dict[str, Any]:
        self._log("GOOGLE_CALENDAR_INTEGRATION_CONNECTION_QUERY", tool_name=tool_name, input=input, **_connection_lookup_diagnostics(self.tenant_id, PROVIDER))
        conn = self.connection_service.get_connection(self.tenant_id, PROVIDER)
        self._log("GOOGLE_CALENDAR_INTEGRATION_CONNECTION_LOADED", tool_name=tool_name, input=input, conn=conn)
        self._log("GOOGLE_CALENDAR_SERVICE_CALL", tool_name=tool_name, input=input, conn=conn)
        try:
            result = operation()
        except Exception as exc:
            self._log("GOOGLE_CALENDAR_SERVICE_EXCEPTION", tool_name=tool_name, input=input, conn=conn, exception=exc)
            raise
        self._log("GOOGLE_CALENDAR_SERVICE_RESULT", tool_name=tool_name, input=input, conn=conn, result=result)
        return result

    def list_events(self, **kwargs: Any) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            tz = self._tenant_timezone(kwargs.get("timezone"))
            params = {"singleEvents": True, "orderBy": "startTime", "timeZone": tz}
            for src, dest in [("time_min", "timeMin"), ("timeMin", "timeMin"), ("time_max", "timeMax"), ("timeMax", "timeMax"), ("max_results", "maxResults"), ("maxResults", "maxResults")]:
                if kwargs.get(src) is not None:
                    params[dest] = self._normalize_datetime(kwargs[src], tz) if "time" in src.lower() else kwargs[src]
            ok, data, _ = self._request("GET", "/calendars/primary/events", params=params)
            if not ok:
                return {"ok": False, **data}
            events = [{"event_id": e.get("id"), "html_link": e.get("htmlLink"), "title": e.get("summary"), "start": (e.get("start") or {}).get("dateTime") or (e.get("start") or {}).get("date"), "end": (e.get("end") or {}).get("dateTime") or (e.get("end") or {}).get("date")} for e in data.get("items", [])]
            return {"ok": True, "events": events}
        return self._service_call("google_calendar_list_events", kwargs, operation)

    def create_event(self, **kwargs: Any) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            tz = self._tenant_timezone(kwargs.get("timezone") or kwargs.get("timeZone"))
            start_raw = kwargs.get("start") or kwargs.get("start_time") or kwargs.get("startTime")
            start_norm = self._normalize_datetime(start_raw, tz) if start_raw else None
            if start_norm and kwargs.get("force_create") is not True and kwargs.get("confirmed_past_date") is not True:
                try:
                    start_dt = datetime.fromisoformat(str(start_norm).replace("Z", "+00:00"))
                    now_local = datetime.now(ZoneInfo(tz))
                    if start_dt.tzinfo is None:
                        start_dt = start_dt.replace(tzinfo=ZoneInfo(tz))
                    else:
                        start_dt = start_dt.astimezone(ZoneInfo(tz))
                    if start_dt < now_local:
                        self._log("AI_AGENT_CALENDAR_PAST_DATE_BLOCKED", tool_name="google_calendar_create_event", input=kwargs, timezone=tz, start=start_dt.isoformat(), now=now_local.isoformat())
                        return {"ok": False, "message": "calendar_past_date_requires_confirmation", "start": start_dt.isoformat(), "timezone": tz}
                except Exception:
                    pass
            ok, data, _ = self._request("POST", "/calendars/primary/events", json_body=self._event_payload(kwargs))
            if not ok:
                return {"ok": False, **data}
            return {"ok": True, "event_id": data.get("id"), "html_link": data.get("htmlLink"), "title": data.get("summary"), "start": (data.get("start") or {}).get("dateTime") or (data.get("start") or {}).get("date"), "end": (data.get("end") or {}).get("dateTime") or (data.get("end") or {}).get("date")}
        return self._service_call("google_calendar_create_event", kwargs, operation)

    def update_event(self, event_id: str, **kwargs: Any) -> dict[str, Any]:
        input_payload = {"event_id": event_id, **kwargs}
        def operation() -> dict[str, Any]:
            ok, data, _ = self._request("PATCH", f"/calendars/primary/events/{event_id}", json_body=self._event_payload(kwargs))
            if not ok:
                return {"ok": False, **data}
            return {"ok": True, "event_id": data.get("id"), "html_link": data.get("htmlLink"), "title": data.get("summary"), "start": (data.get("start") or {}).get("dateTime"), "end": (data.get("end") or {}).get("dateTime")}
        return self._service_call("google_calendar_update_event", input_payload, operation)

    def delete_event(self, event_id: str) -> dict[str, Any]:
        input_payload = {"event_id": event_id}
        def operation() -> dict[str, Any]:
            ok, data, _ = self._request("DELETE", f"/calendars/primary/events/{event_id}")
            if not ok:
                return {"ok": False, **data}
            return {"ok": True, "deleted": True, "event_id": event_id}
        return self._service_call("google_calendar_delete_event", input_payload, operation)

    def check_availability(self, **kwargs: Any) -> dict[str, Any]:
        def operation() -> dict[str, Any]:
            auth_trace: dict[str, Any] = {"access_token_present": False, "refresh_token_present": False, "refresh_attempted": False, "refresh_success": False, "refresh_failed_reason": None}
            self._log("GOOGLE_CALENDAR_CHECK_AVAILABILITY_START", tool_name="google_calendar_check_availability", input=kwargs, **auth_trace)
            tz = self._tenant_timezone(kwargs.get("timezone"))
            start = kwargs.get("start") or kwargs.get("timeMin") or kwargs.get("time_min")
            end = kwargs.get("end") or kwargs.get("timeMax") or kwargs.get("time_max")
            normalized_start = self._normalize_datetime(start, tz)
            normalized_end = self._normalize_datetime(end, tz)
            missing = [name for name, value in (("timeMin", normalized_start), ("timeMax", normalized_end)) if not value]
            if missing:
                result = {"ok": False, "message": "google_calendar_missing_required_fields", "missing_fields": missing}
                self._log("GOOGLE_CALENDAR_CHECK_AVAILABILITY_VALIDATION_FAILED", tool_name="google_calendar_check_availability", input={"missing_fields": missing}, timezone=tz, **auth_trace)
                return result
            body = {"timeMin": normalized_start, "timeMax": normalized_end, "timeZone": tz, "items": [{"id": "primary"}]}
            self._log("GOOGLE_CALENDAR_CHECK_AVAILABILITY_REQUEST", tool_name="google_calendar_check_availability", input=kwargs, timezone=tz, calendar_id="primary", request_body=body, **auth_trace)
            ok, data, _ = self._request("POST", "/freeBusy", json_body=body, auth_trace=auth_trace)
            self._log("GOOGLE_CALENDAR_CHECK_AVAILABILITY_AUTH_READY", tool_name="google_calendar_check_availability", input=kwargs, timezone=tz, calendar_id="primary", **auth_trace)
            if not ok:
                result = {"ok": False, **data}
                self._log("GOOGLE_CALENDAR_CHECK_AVAILABILITY_RESULT", tool_name="google_calendar_check_availability", input=kwargs, timezone=tz, calendar_id="primary", result=result, **auth_trace)
                return result
            busy = ((data.get("calendars") or {}).get("primary") or {}).get("busy") or []
            from app.services.appointment_policy_service import appointments_for_availability, policy_for_tenant
            policy = policy_for_tenant(self.db, self.tenant_id)
            mode = str(kwargs.get("mode") or "period")
            appointments = appointments_for_availability(start=body["timeMin"], end=body["timeMax"], timezone=tz, busy=busy, policy=policy, mode=mode)
            # Canonical availability contract: ToolResult.data is this object and appointments is its list.
            result = {"ok": True, "busy": busy, "appointments": appointments}
            self._log("GOOGLE_CALENDAR_CHECK_AVAILABILITY_RESULT", tool_name="google_calendar_check_availability", input=kwargs, timezone=tz, calendar_id="primary", result=result, **auth_trace)
            return result
        return self._service_call("google_calendar_check_availability", kwargs, operation)
