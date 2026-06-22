from __future__ import annotations

import os, uuid
from datetime import datetime, timedelta, timezone
from typing import Any
import requests
from sqlalchemy.orm import Session
from app.models.integration_connection import IntegrationConnection
from app.services.integration_connection_service import IntegrationConnectionService

PROVIDER = "google_sheets"
TOKEN_URL = "https://oauth2.googleapis.com/token"
SHEETS_URL = "https://sheets.googleapis.com/v4/spreadsheets"
DRIVE_URL = "https://www.googleapis.com/drive/v3"
NOT_CONNECTED_MESSAGE = "Google Sheets não está conectado para este workspace."


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _client_id() -> str:
    return (os.getenv("GOOGLE_SHEETS_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_OAUTH_CLIENT_ID") or "").strip()


def _client_secret() -> str:
    return (os.getenv("GOOGLE_SHEETS_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET") or os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()


class GoogleSheetsService:
    def __init__(self, db: Session, tenant_id: uuid.UUID | str):
        self.db = db
        self.tenant_id = uuid.UUID(str(tenant_id))
        self.connection_service = IntegrationConnectionService(db)

    def _connection(self) -> IntegrationConnection | None:
        conn = self.connection_service.get_active_connection(self.tenant_id, PROVIDER)
        return conn if conn and conn.auth_type == "oauth2" else None

    def _tokens(self, conn: IntegrationConnection) -> tuple[str | None, str | None]:
        return (IntegrationConnectionService.decrypt_credential(conn.access_token_encrypted), IntegrationConnectionService.decrypt_credential(conn.refresh_token_encrypted))

    def refresh_access_token_if_needed(self, force: bool = False) -> dict[str, Any]:
        conn = self._connection()
        if not conn:
            return {"ok": False, "message": NOT_CONNECTED_MESSAGE}
        if not force and conn.expires_at and conn.expires_at > _now() + timedelta(seconds=60):
            return {"ok": True, "refreshed": False}
        _, refresh = self._tokens(conn)
        if not refresh:
            return {"ok": False, "message": "Refresh token do Google Sheets não está disponível."}
        resp = requests.post(TOKEN_URL, data={"client_id": _client_id(), "client_secret": _client_secret(), "refresh_token": refresh, "grant_type": "refresh_token"}, timeout=15)
        if resp.status_code >= 400:
            return {"ok": False, "message": "google_sheets_refresh_failed", "status_code": resp.status_code}
        data = resp.json(); access = data.get("access_token")
        if not access:
            return {"ok": False, "message": "Resposta de renovação do Google Sheets sem access_token."}
        self.connection_service.update_tokens(tenant_id=self.tenant_id, provider=PROVIDER, access_token=access, expires_at=_now() + timedelta(seconds=int(data.get("expires_in") or 3600)))
        return {"ok": True, "refreshed": True}

    def _request(self, method: str, url: str, *, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None, retry: bool = True) -> tuple[bool, Any, int]:
        conn = self._connection()
        if not conn:
            return False, {"message": NOT_CONNECTED_MESSAGE}, 0
        if conn.expires_at and conn.expires_at <= _now() + timedelta(seconds=60):
            refreshed = self.refresh_access_token_if_needed(force=True)
            if not refreshed.get("ok"):
                return False, refreshed, 0
            conn = self._connection()
        access, _ = self._tokens(conn)
        if not access:
            return False, {"message": NOT_CONNECTED_MESSAGE}, 0
        resp = requests.request(method, url, headers={"Authorization": f"Bearer {access}", "Accept": "application/json", "Content-Type": "application/json"}, params=params, json=json_body, timeout=20)
        if resp.status_code == 401 and retry:
            refreshed = self.refresh_access_token_if_needed(force=True)
            if refreshed.get("ok"):
                return self._request(method, url, params=params, json_body=json_body, retry=False)
        if resp.status_code >= 400:
            try: body = resp.json()
            except Exception: body = resp.text
            return False, {"message": "Erro ao chamar Google Sheets.", "status_code": resp.status_code, "api_error": body}, resp.status_code
        return True, ({} if resp.status_code == 204 or not resp.content else resp.json()), resp.status_code

    def list_spreadsheets(self, **kwargs: Any) -> dict[str, Any]:
        params = {"q": "mimeType = 'application/vnd.google-apps.spreadsheet' and trashed=false", "pageSize": int(kwargs.get("page_size") or kwargs.get("max_results") or 10), "fields": "files(id,name,modifiedTime,webViewLink)"}
        query = str(kwargs.get("query") or kwargs.get("q") or "").strip().replace("'", "\\'")
        if query:
            params["q"] = f"name contains '{query}' and " + params["q"]
        ok, data, _ = self._request("GET", f"{DRIVE_URL}/files", params=params)
        if not ok: return {"ok": False, **data}
        return {"ok": True, "spreadsheets": [{"name": f.get("name"), "modified_at": f.get("modifiedTime"), "web_link": f.get("webViewLink"), "spreadsheet_id": f.get("id")} for f in data.get("files", [])]}

    def read_sheet(self, **kwargs: Any) -> dict[str, Any]:
        sid = str(kwargs.get("spreadsheet_id") or kwargs.get("id") or "").strip(); rng = str(kwargs.get("range") or kwargs.get("sheet_range") or "A1:Z20")
        if not sid: return {"ok": False, "message": "spreadsheet_id obrigatório para ler planilha."}
        ok, meta, _ = self._request("GET", f"{SHEETS_URL}/{sid}", params={"fields": "properties.title,sheets(properties(title))"})
        if not ok: return {"ok": False, **meta}
        ok, data, _ = self._request("GET", f"{SHEETS_URL}/{sid}/values/{rng}")
        if not ok: return {"ok": False, **data}
        return {"ok": True, "sheet": {"name": (meta.get("properties") or {}).get("title"), "range": data.get("range"), "rows": data.get("values", [])}}

    def append_row(self, **kwargs: Any) -> dict[str, Any]:
        sid = str(kwargs.get("spreadsheet_id") or "").strip(); rng = str(kwargs.get("range") or "A1"); values = kwargs.get("values") or kwargs.get("row") or []
        if not sid or not isinstance(values, list): return {"ok": False, "message": "spreadsheet_id e values são obrigatórios."}
        ok, data, _ = self._request("POST", f"{SHEETS_URL}/{sid}/values/{rng}:append", params={"valueInputOption": kwargs.get("value_input_option") or "USER_ENTERED", "insertDataOption": "INSERT_ROWS"}, json_body={"values": [values]})
        return {"ok": ok, **({"append": {"updated_range": data.get("updates", {}).get("updatedRange"), "updated_rows": data.get("updates", {}).get("updatedRows")}} if ok else data)}

    def update_row(self, **kwargs: Any) -> dict[str, Any]:
        sid = str(kwargs.get("spreadsheet_id") or "").strip(); rng = str(kwargs.get("range") or kwargs.get("row_range") or ""); values = kwargs.get("values") or kwargs.get("row") or []
        if not sid or not rng or not isinstance(values, list): return {"ok": False, "message": "spreadsheet_id, range e values são obrigatórios."}
        ok, data, _ = self._request("PUT", f"{SHEETS_URL}/{sid}/values/{rng}", params={"valueInputOption": kwargs.get("value_input_option") or "USER_ENTERED"}, json_body={"values": [values]})
        return {"ok": ok, **({"update": {"updated_range": data.get("updatedRange"), "updated_rows": data.get("updatedRows")}} if ok else data)}

    def create_spreadsheet(self, **kwargs: Any) -> dict[str, Any]:
        title = str(kwargs.get("title") or kwargs.get("name") or "Nova planilha")
        ok, data, _ = self._request("POST", SHEETS_URL, json_body={"properties": {"title": title}})
        if not ok: return {"ok": False, **data}
        return {"ok": True, "spreadsheet": {"name": (data.get("properties") or {}).get("title") or title, "web_link": data.get("spreadsheetUrl"), "spreadsheet_id": data.get("spreadsheetId")}}
