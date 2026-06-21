from __future__ import annotations

import os, uuid
from datetime import datetime, timedelta, timezone
from typing import Any
import requests
from sqlalchemy.orm import Session
from app.models.integration_connection import IntegrationConnection
from app.services.integration_connection_service import IntegrationConnectionService

PROVIDER = "google_drive"
TOKEN_URL = "https://oauth2.googleapis.com/token"
DRIVE_URL = "https://www.googleapis.com/drive/v3"
UPLOAD_URL = "https://www.googleapis.com/upload/drive/v3"
DOCS_URL = "https://docs.googleapis.com/v1"
NOT_CONNECTED_MESSAGE = "Google Drive não está conectado para este workspace."


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _client_id() -> str:
    return (os.getenv("GOOGLE_DRIVE_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_OAUTH_CLIENT_ID") or "").strip()


def _client_secret() -> str:
    return (os.getenv("GOOGLE_DRIVE_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET") or os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip()


class GoogleDriveService:
    def __init__(self, db: Session, tenant_id: uuid.UUID | str):
        self.db = db
        self.tenant_id = uuid.UUID(str(tenant_id))
        self.connection_service = IntegrationConnectionService(db)

    def _connection(self) -> IntegrationConnection | None:
        conn = self.connection_service.get_active_connection(self.tenant_id, PROVIDER)
        return conn if conn and conn.auth_type == "oauth2" else None

    def _tokens(self, conn: IntegrationConnection) -> tuple[str | None, str | None]:
        return (
            IntegrationConnectionService.decrypt_credential(conn.access_token_encrypted),
            IntegrationConnectionService.decrypt_credential(conn.refresh_token_encrypted),
        )

    def refresh_access_token_if_needed(self, force: bool = False) -> dict[str, Any]:
        conn = self._connection()
        if not conn:
            return {"ok": False, "message": NOT_CONNECTED_MESSAGE}
        if not force and conn.expires_at and conn.expires_at > _now() + timedelta(seconds=60):
            return {"ok": True, "refreshed": False}
        _, refresh = self._tokens(conn)
        if not refresh:
            return {"ok": False, "message": "Refresh token do Google Drive não está disponível."}
        resp = requests.post(TOKEN_URL, data={"client_id": _client_id(), "client_secret": _client_secret(), "refresh_token": refresh, "grant_type": "refresh_token"}, timeout=15)
        if resp.status_code >= 400:
            return {"ok": False, "message": "google_drive_refresh_failed", "status_code": resp.status_code}
        data = resp.json()
        access = data.get("access_token")
        if not access:
            return {"ok": False, "message": "Resposta de renovação do Google Drive sem access_token."}
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
            return False, {"message": "Erro ao chamar Google Drive.", "status_code": resp.status_code, "api_error": body}, resp.status_code
        return True, ({} if resp.status_code == 204 or not resp.content else resp.json()), resp.status_code

    def _file_out(self, f: dict[str, Any]) -> dict[str, Any]:
        return {"name": f.get("name"), "type": f.get("mimeType"), "modified_at": f.get("modifiedTime"), "web_link": f.get("webViewLink"), "file_id": f.get("id")}

    def list_files(self, **kwargs: Any) -> dict[str, Any]:
        params = {"pageSize": int(kwargs.get("page_size") or kwargs.get("max_results") or 10), "fields": "files(id,name,mimeType,modifiedTime,webViewLink)"}
        ok, data, _ = self._request("GET", f"{DRIVE_URL}/files", params=params)
        if not ok: return {"ok": False, **data}
        return {"ok": True, "files": [self._file_out(f) for f in data.get("files", [])]}

    def search_files(self, **kwargs: Any) -> dict[str, Any]:
        query = str(kwargs.get("query") or kwargs.get("q") or kwargs.get("name") or "").replace("'", "\\'")
        params = {"q": f"name contains '{query}' and trashed=false" if query else "trashed=false", "pageSize": int(kwargs.get("page_size") or 10), "fields": "files(id,name,mimeType,modifiedTime,webViewLink)"}
        ok, data, _ = self._request("GET", f"{DRIVE_URL}/files", params=params)
        if not ok: return {"ok": False, **data}
        return {"ok": True, "files": [self._file_out(f) for f in data.get("files", [])]}

    def read_file(self, **kwargs: Any) -> dict[str, Any]:
        file_id = str(kwargs.get("file_id") or kwargs.get("id") or "")
        if not file_id: return {"ok": False, "message": "file_id obrigatório para ler arquivo."}
        ok, meta, _ = self._request("GET", f"{DRIVE_URL}/files/{file_id}", params={"fields":"id,name,mimeType,modifiedTime"})
        if not ok: return {"ok": False, **meta}
        mime = meta.get("mimeType")
        if mime == "application/vnd.google-apps.document":
            ok, doc, _ = self._request("GET", f"{DOCS_URL}/documents/{file_id}")
            if not ok: return {"ok": False, **doc}
            text = "".join((el.get("textRun") or {}).get("content", "") for c in (doc.get("body") or {}).get("content", []) for el in (c.get("paragraph") or {}).get("elements", []))
        else:
            ok, text, _ = self._request("GET", f"{DRIVE_URL}/files/{file_id}/export", params={"mimeType":"text/plain"}) if str(mime).startswith("application/vnd.google-apps") else (False, {"message":"Tipo de arquivo não suportado para leitura textual."}, 0)
            if not ok: return {"ok": False, **(text if isinstance(text, dict) else {"message": str(text)})}
        return {"ok": True, "document": {"name": meta.get("name"), "type": mime, "modified_at": meta.get("modifiedTime"), "text": text[:12000]}}

    def create_document(self, **kwargs: Any) -> dict[str, Any]:
        title = str(kwargs.get("title") or kwargs.get("name") or "Novo documento")
        ok, data, _ = self._request("POST", f"{DOCS_URL}/documents", json_body={"title": title})
        if not ok: return {"ok": False, **data}
        return {"ok": True, "document": {"name": data.get("title") or title, "type": "application/vnd.google-apps.document", "web_link": f"https://docs.google.com/document/d/{data.get('documentId')}/edit"}}

    def create_folder(self, **kwargs: Any) -> dict[str, Any]:
        name = str(kwargs.get("name") or kwargs.get("title") or "Nova pasta")
        ok, data, _ = self._request("POST", f"{DRIVE_URL}/files", json_body={"name": name, "mimeType": "application/vnd.google-apps.folder"})
        if not ok: return {"ok": False, **data}
        return {"ok": True, "folder": self._file_out(data)}
