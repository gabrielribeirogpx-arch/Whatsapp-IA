from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from app.models.integration_connection import IntegrationConnection
from app.models.pending_action import PendingAction
from app.routers.mcp import _gmail_tools_out
from app.services.ai_agent_service import run_agent_for_tenant
from app.services.integration_connection_service import IntegrationConnectionService
from app.services.pending_action_service import EMAIL_SEND_CONFIRMATION
from app.tools.adapters.gmail_tool_adapter import GmailToolAdapter, gmail_tool_definitions
from app.tools.context import ToolContext


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
