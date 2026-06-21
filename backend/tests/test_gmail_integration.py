from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models.integration_connection import IntegrationConnection
from app.models.pending_action import PendingAction
from app.routers import gmail_integration as gmail_router_module
from app.routers.gmail_integration import create_oauth_state, router as gmail_router, verify_oauth_state
from app.routers.mcp import _gmail_tools_out
from app.services.ai_agent_service import run_agent_for_tenant
from app.services.integration_connection_service import IntegrationConnectionService
from app.services.pending_action_service import EMAIL_SEND_CONFIRMATION
from app.services.tenant_service import get_current_tenant
from app.tools.adapters.gmail_tool_adapter import GmailToolAdapter, gmail_tool_definitions
from app.tools.context import ToolContext
from tests.test_integration_connection_service import FakeDb


class FakeDB:
    def __init__(self, connection=None):
        self.connection = connection
        self.pending = []

    def query(self, model):
        return self

    def filter(self, *args, **kwargs):
        return self

    def order_by(self, *args, **kwargs):
        return self

    def first(self):
        return self.pending[-1] if self.pending else None

    def delete(self, synchronize_session=False):
        count = len(self.pending)
        self.pending.clear()
        return count

    def add(self, row):
        row.id = uuid.uuid4()
        self.pending.append(row)

    def flush(self):
        pass


class StubConnectionService:
    def __init__(self, db):
        self.db = db

    def get_active_connection(self, tenant_id, provider):
        return self.db.connection

    def get_connection(self, tenant_id, provider):
        return self.db.connection


def active_connection(tenant_id: uuid.UUID):
    return IntegrationConnection(tenant_id=tenant_id, provider="gmail", auth_type="oauth2", status="active", access_token_encrypted="access", refresh_token_encrypted="refresh", expires_at=datetime.utcnow() + timedelta(hours=1), scopes_json=[], metadata_json={"account_email": "user@example.com"})


def test_gmail_tools_exposed_only_when_connected(monkeypatch):
    tenant_id = uuid.uuid4()
    monkeypatch.setattr(IntegrationConnectionService, "get_active_connection", lambda self, tenant, provider: active_connection(tenant) if provider == "gmail" else None)
    assert {tool["tool_id"] for tool in _gmail_tools_out(FakeDB(), tenant_id)} == {tool["tool_id"] for tool in gmail_tool_definitions(connected=True)}
    monkeypatch.setattr(IntegrationConnectionService, "get_active_connection", lambda self, tenant, provider: None)
    assert _gmail_tools_out(FakeDB(), tenant_id) == []


def test_gmail_adapter_list_search_draft_and_send(monkeypatch):
    tenant_id = uuid.uuid4()
    db = FakeDB(active_connection(tenant_id))
    monkeypatch.setattr("app.services.gmail_service.IntegrationConnectionService", StubConnectionService)
    monkeypatch.setattr(IntegrationConnectionService, "decrypt_credential_strict", staticmethod(lambda value: value))

    calls = []
    def fake_request(method, url, **kwargs):
        calls.append((method, url, kwargs))
        class Resp:
            status_code = 200
            content = b"{}"
            text = "{}"
            def json(self):
                if url.endswith("/messages"):
                    return {"messages": [{"id": "m1"}]}
                if "/messages/m1" in url:
                    return {"id": "m1", "threadId": "t1", "snippet": "Resumo", "payload": {"headers": [{"name": "Subject", "value": "Olá"}, {"name": "From", "value": "a@example.com"}]}}
                if url.endswith("/drafts"):
                    return {"id": "d1", "message": {"id": "m2"}}
                if url.endswith("/messages/send"):
                    return {"id": "m3", "threadId": "t3"}
                return {}
        return Resp()
    monkeypatch.setattr("app.services.gmail_service.requests.request", fake_request)

    adapter = GmailToolAdapter(db)
    ctx = ToolContext(tenant_id=tenant_id)
    assert adapter.execute("gmail_list_messages", {"max_results": 1}, ctx).ok is True
    assert adapter.execute("gmail_search_messages", {"query": "from:a@example.com"}, ctx).ok is True
    assert adapter.execute("gmail_create_draft", {"to": "b@example.com", "subject": "S", "body": "B"}, ctx).ok is True
    assert adapter.execute("gmail_send_email", {"to": "b@example.com", "subject": "S", "body": "B"}, ctx).ok is True


def test_gmail_send_creates_pending_and_confirmation_sends(monkeypatch):
    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    db = FakeDB()
    mcp_tools = [{"tool_id": "gmail_send_email", "metadata": {"provider": "gmail"}}]
    result = run_agent_for_tenant(db, tenant_id, "envie um e-mail para teste@example.com", "", ["chamar_mcp"], {}, options={"conversation_id": str(conversation_id), "mcp_tools": mcp_tools})
    assert result.message == "Você quer enviar este e-mail?"
    assert db.pending and db.pending[-1].action_type == EMAIL_SEND_CONFIRMATION

    sent = {}
    def fake_execute(self, tool_type, tool_id, input, context, config=None):
        sent.update({"tool_type": tool_type, "tool_id": tool_id, "input": input})
        from app.tools.base import ToolResult
        return ToolResult(True, "gmail", tool_id="gmail_send_email", output={"ok": True, "message_id": "m1"})
    monkeypatch.setattr("app.tools.registry.ToolRegistry.execute", fake_execute)
    result = run_agent_for_tenant(db, tenant_id, "sim", "", ["chamar_mcp"], {}, options={"conversation_id": str(conversation_id), "mcp_tools": mcp_tools})
    assert result.message == "E-mail enviado com sucesso."
    assert sent["tool_id"] == "gmail_send_email"


def test_gmail_send_cancel_does_not_send(monkeypatch):
    tenant_id = uuid.uuid4()
    conversation_id = uuid.uuid4()
    db = FakeDB()
    pending = PendingAction(tenant_id=tenant_id, conversation_id=conversation_id, action_type=EMAIL_SEND_CONFIRMATION, payload_json={"to": "x@example.com"}, expires_at=datetime.utcnow() + timedelta(minutes=5))
    db.add(pending)
    called = False
    def fake_execute(*args, **kwargs):
        nonlocal called
        called = True
    monkeypatch.setattr("app.tools.registry.ToolRegistry.execute", fake_execute)
    result = run_agent_for_tenant(db, tenant_id, "não", "", ["chamar_mcp"], {}, options={"conversation_id": str(conversation_id), "mcp_tools": [{"tool_id": "gmail_send_email"}]})
    assert result.message == "Tudo bem, operação cancelada."
    assert called is False
    assert db.pending == []


@pytest.fixture
def gmail_oauth_env(monkeypatch):
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", "integration-test-secret")
    monkeypatch.setenv("GMAIL_STATE_SECRET", "state-secret")
    monkeypatch.setenv("GMAIL_CLIENT_ID", "gmail-client-id")
    monkeypatch.setenv("GMAIL_CLIENT_SECRET", "gmail-client-secret")
    monkeypatch.setenv("GMAIL_REDIRECT_URI", "https://app.example.com/api/integrations/gmail/callback")
    monkeypatch.setenv("FRONTEND_URL", "https://frontend.example.com")


def _gmail_client(tenant_id: uuid.UUID, db: FakeDb) -> TestClient:
    app = FastAPI()
    app.include_router(gmail_router, prefix="/api")
    app.dependency_overrides[get_current_tenant] = lambda: SimpleNamespace(id=tenant_id)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def _signed_state(payload: dict) -> str:
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_json).decode("ascii").rstrip("=")
    signature = hmac.new(b"state-secret", payload_b64.encode("ascii"), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"{payload_b64}.{sig_b64}"


def test_gmail_state_contains_provider_and_rejects_google_calendar_provider(gmail_oauth_env):
    tenant_id = uuid.uuid4()
    state = create_oauth_state(tenant_id, nonce="gmail-nonce")

    payload = verify_oauth_state(state)

    assert payload["tenant_id"] == str(tenant_id)
    assert payload["provider"] == "gmail"
    google_calendar_state = _signed_state({
        "tenant_id": str(tenant_id),
        "provider": "google_calendar",
        "nonce": "n",
        "iat": int(datetime.utcnow().timestamp()),
    })
    with pytest.raises(Exception):
        verify_oauth_state(google_calendar_state)


def test_gmail_connect_url_route_redirects_to_gmail_oauth(gmail_oauth_env, monkeypatch):
    tenant_id = uuid.uuid4()
    monkeypatch.setattr(
        gmail_router_module,
        "resolve_current_tenant",
        lambda *args, **kwargs: SimpleNamespace(tenant=SimpleNamespace(id=tenant_id), source="test"),
    )

    response = _gmail_client(tenant_id, FakeDb()).get("/api/integrations/gmail/connect-url?tenant_slug=tenant-ok", follow_redirects=False)

    assert response.status_code == 302
    params = parse_qs(urlparse(response.headers["location"]).query)
    assert params["client_id"] == ["gmail-client-id"]
    assert params["redirect_uri"] == ["https://app.example.com/api/integrations/gmail/callback"]
    assert verify_oauth_state(params["state"][0])["provider"] == "gmail"


def test_gmail_connect_url_uses_gmail_callback_and_scopes(gmail_oauth_env, monkeypatch):
    tenant_id = uuid.uuid4()
    monkeypatch.setattr(
        gmail_router_module,
        "resolve_current_tenant",
        lambda *args, **kwargs: SimpleNamespace(tenant=SimpleNamespace(id=tenant_id), source="test"),
    )

    response = _gmail_client(tenant_id, FakeDb()).get("/api/integrations/gmail/connect-url?tenant_slug=tenant-ok", follow_redirects=False)

    assert response.status_code == 302
    params = parse_qs(urlparse(response.headers["location"]).query)
    assert params["redirect_uri"] == ["https://app.example.com/api/integrations/gmail/callback"]
    assert "/api/integrations/gmail/callback" in params["redirect_uri"][0]
    assert "google-calendar/callback" not in params["redirect_uri"][0]
    for scope in gmail_router_module.SCOPES:
        assert scope in params["scope"][0].split()


def test_gmail_callback_persists_gmail_without_changing_google_calendar(gmail_oauth_env, monkeypatch):
    tenant_id = uuid.uuid4()
    db = FakeDb()
    service = IntegrationConnectionService(db)  # type: ignore[arg-type]
    service.upsert_connection(
        tenant_id=tenant_id,
        provider="google_calendar",
        auth_type="oauth2",
        access_token="calendar-access",
        refresh_token="calendar-refresh",
        metadata={"account_email": "calendar@example.com"},
    )
    calendar_connection = service.get_connection(tenant_id, "google_calendar")
    assert calendar_connection is not None
    calendar_access_before = calendar_connection.access_token_encrypted
    state = create_oauth_state(tenant_id, nonce="callback-nonce")

    class Response:
        status_code = 200
        def __init__(self, payload): self._payload = payload
        def json(self): return self._payload

    monkeypatch.setattr(
        gmail_router_module.requests,
        "post",
        lambda *args, **kwargs: Response({
            "access_token": "gmail-access",
            "refresh_token": "gmail-refresh",
            "expires_in": 3600,
            "scope": "openid email profile",
        }),
    )
    monkeypatch.setattr(
        gmail_router_module.requests,
        "get",
        lambda *args, **kwargs: Response({"email": "gmail@example.com"}),
    )

    response = _gmail_client(tenant_id, db).get(f"/api/integrations/gmail/callback?code=auth-code&state={state}", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "https://frontend.example.com/dashboard/ai/mcp?integration=gmail&status=connected"
    gmail_connection = service.get_connection(tenant_id, "gmail")
    google_connection = service.get_connection(tenant_id, "google_calendar")
    assert gmail_connection is not None
    assert gmail_connection.provider == "gmail"
    assert gmail_connection.auth_type == "oauth2"
    assert gmail_connection.status == "active"
    assert google_connection is calendar_connection
    assert google_connection.access_token_encrypted == calendar_access_before
    status = _gmail_client(tenant_id, db).get("/api/integrations/gmail/status")
    assert status.status_code == 200
    assert status.json()["provider"] == "gmail"
    assert status.json()["connected"] is True


def test_gmail_callback_rejects_google_calendar_state_and_keeps_connections_independent(gmail_oauth_env):
    tenant_id = uuid.uuid4()
    db = FakeDb()
    service = IntegrationConnectionService(db)  # type: ignore[arg-type]
    service.upsert_connection(tenant_id=tenant_id, provider="google_calendar", auth_type="oauth2", access_token="calendar-access")
    google_calendar_state = _signed_state({
        "tenant_id": str(tenant_id),
        "provider": "google_calendar",
        "nonce": "n",
        "iat": int(datetime.utcnow().timestamp()),
    })

    response = _gmail_client(tenant_id, db).get(f"/api/integrations/gmail/callback?code=auth-code&state={google_calendar_state}", follow_redirects=False)

    assert response.status_code == 302
    assert response.headers["location"] == "https://frontend.example.com/dashboard/ai/mcp?integration=gmail&status=error"
    assert service.get_connection(tenant_id, "gmail") is None
    assert service.get_connection(tenant_id, "google_calendar") is not None
