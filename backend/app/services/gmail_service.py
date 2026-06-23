from __future__ import annotations

import base64
import os
import uuid
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any

import requests
from sqlalchemy.orm import Session

from app.models.integration_connection import IntegrationConnection
from app.services.integration_connection_service import GOOGLE_RECONNECT_MESSAGE, IntegrationConnectionService, is_google_auth_error

PROVIDER = "gmail"
BASE_URL = "https://gmail.googleapis.com/gmail/v1/users/me"
TOKEN_URL = "https://oauth2.googleapis.com/token"
NOT_CONNECTED_MESSAGE = "Gmail não está conectado para este workspace."


def _now_utc_naive() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class GmailService:
    def __init__(self, db: Session, tenant_id: uuid.UUID | str):
        self.db = db
        self.tenant_id = uuid.UUID(str(tenant_id))
        self.connection_service = IntegrationConnectionService(db)

    def _connection(self) -> IntegrationConnection | None:
        conn = self.connection_service.get_active_connection(self.tenant_id, PROVIDER)
        return conn if conn and conn.auth_type == "oauth2" else None

    def _tokens(self, conn: IntegrationConnection) -> tuple[str | None, str | None]:
        return (
            IntegrationConnectionService.decrypt_credential_strict(conn.access_token_encrypted),
            IntegrationConnectionService.decrypt_credential_strict(conn.refresh_token_encrypted),
        )

    def refresh_access_token_if_needed(self, force: bool = False) -> dict[str, Any]:
        conn = self._connection()
        if not conn:
            return {"ok": False, "message": NOT_CONNECTED_MESSAGE}
        if not force and conn.expires_at and conn.expires_at > _now_utc_naive() + timedelta(seconds=60):
            return {"ok": True, "refreshed": False}
        _access, refresh = self._tokens(conn)
        if not refresh:
            return {"ok": False, "message": "Refresh token do Gmail não está disponível."}
        response = requests.post(
            TOKEN_URL,
            data={
                "client_id": (os.getenv("GMAIL_CLIENT_ID") or os.getenv("GOOGLE_CLIENT_ID") or os.getenv("GOOGLE_OAUTH_CLIENT_ID") or "").strip(),
                "client_secret": (os.getenv("GMAIL_CLIENT_SECRET") or os.getenv("GOOGLE_CLIENT_SECRET") or os.getenv("GOOGLE_OAUTH_CLIENT_SECRET") or "").strip(),
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
            timeout=15,
        )
        if response.status_code >= 400:
            try:
                body = response.json()
            except Exception:
                body = getattr(response, "text", "")
            if is_google_auth_error(response.status_code, body):
                self.connection_service.mark_google_connection_revoked(self.tenant_id, PROVIDER)
                return {"ok": False, "message": GOOGLE_RECONNECT_MESSAGE, "status_code": response.status_code, "api_error": body}
            return {"ok": False, "message": "Falha ao renovar token do Gmail.", "status_code": response.status_code}
        payload = response.json()
        self.connection_service.upsert_connection(
            tenant_id=self.tenant_id,
            provider=PROVIDER,
            auth_type="oauth2",
            access_token=payload.get("access_token"),
            refresh_token=refresh,
            expires_at=datetime.utcnow() + timedelta(seconds=int(payload.get("expires_in") or 3600)),
            scopes=conn.scopes or [],
            metadata=conn.metadata_json or {},
        )
        return {"ok": True, "refreshed": True}

    def _request(self, method: str, path: str, *, params: dict[str, Any] | None = None, json_body: dict[str, Any] | None = None, retry: bool = True) -> tuple[bool, Any, int]:
        conn = self._connection()
        if not conn:
            return False, {"message": NOT_CONNECTED_MESSAGE}, 0
        access, _refresh = self._tokens(conn)
        if not access:
            return False, {"message": NOT_CONNECTED_MESSAGE}, 0
        resp = requests.request(method, f"{BASE_URL}{path}", headers={"Authorization": f"Bearer {access}", "Accept": "application/json"}, params=params, json=json_body, timeout=15)
        if resp.status_code == 401 and retry:
            refreshed = self.refresh_access_token_if_needed(force=True)
            if refreshed.get("ok"):
                return self._request(method, path, params=params, json_body=json_body, retry=False)
            return False, refreshed, resp.status_code
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            if is_google_auth_error(resp.status_code, body):
                self.connection_service.mark_google_connection_revoked(self.tenant_id, PROVIDER)
                return False, {"message": GOOGLE_RECONNECT_MESSAGE, "status_code": resp.status_code, "api_error": body}, resp.status_code
            return False, {"message": "Erro ao chamar Gmail.", "status_code": resp.status_code, "api_error": body}, resp.status_code
        return True, ({} if resp.status_code == 204 or not resp.content else resp.json()), resp.status_code

    @staticmethod
    def _message_summary(item: dict[str, Any]) -> dict[str, Any]:
        headers = {h.get("name", "").lower(): h.get("value") for h in ((item.get("payload") or {}).get("headers") or [])}
        return {"message_id": item.get("id"), "thread_id": item.get("threadId"), "snippet": item.get("snippet"), "from": headers.get("from"), "to": headers.get("to"), "subject": headers.get("subject"), "date": headers.get("date")}

    def list_messages(self, **kwargs: Any) -> dict[str, Any]:
        ok, data, _ = self._request("GET", "/messages", params={"maxResults": kwargs.get("max_results") or kwargs.get("maxResults") or 10, "labelIds": kwargs.get("label_ids") or kwargs.get("labelIds") or "INBOX"})
        if not ok:
            return {"ok": False, **data}
        messages = []
        for ref in data.get("messages", [])[: int(kwargs.get("max_results") or 10)]:
            detail = self.read_message(str(ref.get("id")), format="metadata")
            if detail.get("ok"):
                messages.append(detail["message"])
        return {"ok": True, "messages": messages}

    def search_messages(self, **kwargs: Any) -> dict[str, Any]:
        query = str(kwargs.get("query") or kwargs.get("q") or "").strip()
        ok, data, _ = self._request("GET", "/messages", params={"q": query, "maxResults": kwargs.get("max_results") or kwargs.get("maxResults") or 10})
        if not ok:
            return {"ok": False, **data}
        messages = []
        for ref in data.get("messages", [])[: int(kwargs.get("max_results") or 10)]:
            detail = self.read_message(str(ref.get("id")), format="metadata")
            if detail.get("ok"):
                messages.append(detail["message"])
        return {"ok": True, "query": query, "messages": messages}

    def read_message(self, message_id: str | None = None, **kwargs: Any) -> dict[str, Any]:
        message_id = message_id or kwargs.get("message_id") or kwargs.get("id")
        if not message_id and kwargs.get("latest"):
            listed = self.list_messages(max_results=1)
            if not listed.get("ok") or not listed.get("messages"):
                return listed
            message_id = listed["messages"][0]["message_id"]
        if not message_id:
            return {"ok": False, "message": "message_id é obrigatório."}
        ok, data, _ = self._request("GET", f"/messages/{message_id}", params={"format": kwargs.get("format") or "full"})
        if not ok:
            return {"ok": False, **data}
        return {"ok": True, "message": self._message_summary(data) | {"raw": data if kwargs.get("include_raw") else None}}

    @staticmethod
    def _raw_email(to: str, subject: str, body: str, cc: str | None = None, bcc: str | None = None) -> str:
        msg = EmailMessage(); msg["To"] = to; msg["Subject"] = subject
        if cc: msg["Cc"] = cc
        if bcc: msg["Bcc"] = bcc
        msg.set_content(body)
        return base64.urlsafe_b64encode(msg.as_bytes()).decode().rstrip("=")

    def create_draft(self, **kwargs: Any) -> dict[str, Any]:
        raw = kwargs.get("raw") or self._raw_email(str(kwargs.get("to") or ""), str(kwargs.get("subject") or ""), str(kwargs.get("body") or ""), kwargs.get("cc"), kwargs.get("bcc"))
        ok, data, _ = self._request("POST", "/drafts", json_body={"message": {"raw": raw}})
        if not ok:
            return {"ok": False, **data}
        return {"ok": True, "draft_id": data.get("id"), "message_id": (data.get("message") or {}).get("id")}

    def send_email(self, **kwargs: Any) -> dict[str, Any]:
        if kwargs.get("draft_id"):
            ok, data, _ = self._request("POST", "/drafts/send", json_body={"id": kwargs.get("draft_id")})
        else:
            raw = kwargs.get("raw") or self._raw_email(str(kwargs.get("to") or ""), str(kwargs.get("subject") or ""), str(kwargs.get("body") or ""), kwargs.get("cc"), kwargs.get("bcc"))
            ok, data, _ = self._request("POST", "/messages/send", json_body={"raw": raw})
        if not ok:
            return {"ok": False, **data}
        return {"ok": True, "message_id": data.get("id"), "thread_id": data.get("threadId")}
