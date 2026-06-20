from __future__ import annotations

import logging
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from sqlalchemy.orm import Session

from app.models.integration_connection import IntegrationConnection
from app.services.integration_connection_service import IntegrationConnectionService
from app.tools.context import sanitize_metadata

logger = logging.getLogger(__name__)

PROVIDER = "google_calendar"
BASE_URL = "https://www.googleapis.com/calendar/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
NOT_CONNECTED_MESSAGE = "Google Calendar não está conectado para este workspace."
DEFAULT_TIMEZONE = "America/Sao_Paulo"


def _now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class GoogleCalendarService:
    def __init__(self, db: Session, tenant_id: uuid.UUID | str):
        self.db = db
        self.tenant_id = uuid.UUID(str(tenant_id))
        self.connection_service = IntegrationConnectionService(db)

    def _connection(self) -> IntegrationConnection | None:
        conn = self.connection_service.get_active_connection(self.tenant_id, PROVIDER)
        if not conn or conn.auth_type != "oauth2":
            logger.warning("GOOGLE_CALENDAR_NOT_CONNECTED tenant_id=%s", self.tenant_id)
            return None
        return conn

    def _tokens(self, conn: IntegrationConnection) -> tuple[str | None, str | None]:
        return (
            IntegrationConnectionService.decrypt_credential(conn.access_token_encrypted),
            IntegrationConnectionService.decrypt_credential(conn.refresh_token_encrypted),
        )

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
        conn = self._connection()
        if not conn:
            return {"ok": False, "message": NOT_CONNECTED_MESSAGE}
        if not force and conn.expires_at and conn.expires_at > _now_utc_naive() + timedelta(seconds=60):
            return {"ok": True, "refreshed": False}
        _access, refresh = self._tokens(conn)
        if not refresh:
            return {"ok": False, "message": "Refresh token do Google Calendar não está disponível."}
        logger.info("GOOGLE_CALENDAR_TOKEN_REFRESH tenant_id=%s", self.tenant_id)
        try:
            resp = requests.post(TOKEN_URL, data={
                "client_id": os.getenv("GOOGLE_CALENDAR_CLIENT_ID", ""),
                "client_secret": os.getenv("GOOGLE_CALENDAR_CLIENT_SECRET", ""),
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            }, timeout=15)
            if resp.status_code >= 400:
                logger.warning("GOOGLE_CALENDAR_TOKEN_REFRESH_FAILED tenant_id=%s status=%s", self.tenant_id, resp.status_code)
                return {"ok": False, "message": "Não foi possível renovar o acesso ao Google Calendar."}
            data = resp.json()
            access = data.get("access_token")
            if not access:
                return {"ok": False, "message": "Resposta de renovação do Google Calendar sem access_token."}
            expires_at = _now_utc_naive() + timedelta(seconds=int(data.get("expires_in") or 3600))
            self.connection_service.update_tokens(tenant_id=self.tenant_id, provider=PROVIDER, access_token=access, expires_at=expires_at)
            return {"ok": True, "refreshed": True}
        except requests.RequestException:
            logger.exception("GOOGLE_CALENDAR_TOKEN_REFRESH_FAILED tenant_id=%s", self.tenant_id)
            return {"ok": False, "message": "Não foi possível renovar o acesso ao Google Calendar."}

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None, retry: bool = True) -> tuple[bool, Any, int]:
        conn = self._connection()
        if not conn:
            return False, {"message": NOT_CONNECTED_MESSAGE}, 0
        if conn.expires_at and conn.expires_at <= _now_utc_naive() + timedelta(seconds=60):
            refreshed = self.refresh_access_token_if_needed(force=True)
            if refreshed.get("ok") is False:
                return False, refreshed, 0
            conn = self._connection()
        access, _refresh = self._tokens(conn)
        if not access:
            return False, {"message": NOT_CONNECTED_MESSAGE}, 0
        logger.info("GOOGLE_CALENDAR_SERVICE_REQUEST %s", sanitize_metadata({"tenant_id": str(self.tenant_id), "method": method, "path": path, "params": params}))
        resp = requests.request(method, f"{BASE_URL}{path}", headers={"Authorization": f"Bearer {access}", "Accept": "application/json"}, params=params, json=json_body, timeout=15)
        if resp.status_code == 401 and retry:
            refreshed = self.refresh_access_token_if_needed(force=True)
            if refreshed.get("ok"):
                return self._request(method, path, params=params, json_body=json_body, retry=False)
            return False, refreshed, resp.status_code
        if resp.status_code >= 400:
            logger.warning("GOOGLE_CALENDAR_API_ERROR tenant_id=%s status=%s path=%s", self.tenant_id, resp.status_code, path)
            return False, {"message": "Erro ao chamar Google Calendar.", "status_code": resp.status_code}, resp.status_code
        data = {} if resp.status_code == 204 or not resp.content else resp.json()
        logger.info("GOOGLE_CALENDAR_SERVICE_RESPONSE %s", sanitize_metadata({"tenant_id": str(self.tenant_id), "status": resp.status_code, "path": path}))
        return True, data, resp.status_code

    def list_events(self, **kwargs: Any) -> dict[str, Any]:
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

    def create_event(self, **kwargs: Any) -> dict[str, Any]:
        ok, data, _ = self._request("POST", "/calendars/primary/events", json_body=self._event_payload(kwargs))
        if not ok:
            return {"ok": False, **data}
        return {"ok": True, "event_id": data.get("id"), "html_link": data.get("htmlLink"), "title": data.get("summary"), "start": (data.get("start") or {}).get("dateTime") or (data.get("start") or {}).get("date"), "end": (data.get("end") or {}).get("dateTime") or (data.get("end") or {}).get("date")}

    def update_event(self, event_id: str, **kwargs: Any) -> dict[str, Any]:
        ok, data, _ = self._request("PATCH", f"/calendars/primary/events/{event_id}", json_body=self._event_payload(kwargs))
        if not ok:
            return {"ok": False, **data}
        return {"ok": True, "event_id": data.get("id"), "html_link": data.get("htmlLink"), "title": data.get("summary"), "start": (data.get("start") or {}).get("dateTime"), "end": (data.get("end") or {}).get("dateTime")}

    def delete_event(self, event_id: str) -> dict[str, Any]:
        ok, data, _ = self._request("DELETE", f"/calendars/primary/events/{event_id}")
        if not ok:
            return {"ok": False, **data}
        return {"ok": True, "deleted": True, "event_id": event_id}

    def check_availability(self, **kwargs: Any) -> dict[str, Any]:
        tz = self._tenant_timezone(kwargs.get("timezone"))
        start = kwargs.get("start") or kwargs.get("timeMin") or kwargs.get("time_min")
        end = kwargs.get("end") or kwargs.get("timeMax") or kwargs.get("time_max")
        body = {"timeMin": self._normalize_datetime(start, tz), "timeMax": self._normalize_datetime(end, tz), "timeZone": tz, "items": [{"id": "primary"}]}
        ok, data, _ = self._request("POST", "/freeBusy", json_body=body)
        if not ok:
            return {"ok": False, **data}
        busy = ((data.get("calendars") or {}).get("primary") or {}).get("busy") or []
        return {"ok": True, "busy": busy, "available_slots": []}
