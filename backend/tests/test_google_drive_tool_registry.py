from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models.integration_connection import IntegrationConnection
from app.models.tenant_mcp import TenantMCPTool
from app.routers.mcp import router
from app.services.tenant_service import get_current_tenant


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows
    def first(self):
        return self._rows[0] if self._rows else None
    def all(self):
        return self._rows


class _ExecuteResult:
    def __init__(self, rows):
        self._rows = rows
    def scalars(self):
        return _ScalarResult(self._rows)


class FakeDb:
    def __init__(self):
        self.connections = []
        self.mcp_tools = []
    def execute(self, statement):
        compiled = statement.compile()
        params = compiled.params
        text = str(compiled)
        rows = self.mcp_tools if "tenant_mcp_tools" in text else self.connections
        tenant_id = params.get("tenant_id_1")
        provider = params.get("provider_1")
        if tenant_id is not None:
            rows = [row for row in rows if row.tenant_id == tenant_id]
        if provider is not None:
            rows = [row for row in rows if getattr(row, "provider", None) == provider]
        return _ExecuteResult(rows)


def _client(db, tenant_id):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_tenant] = lambda: SimpleNamespace(id=tenant_id)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_connected_tenant_sees_google_drive_tools_and_mcp_stays_separate(monkeypatch):
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", "integration-test-secret")
    tenant_id = uuid.uuid4()
    db = FakeDb()
    db.connections.append(IntegrationConnection(tenant_id=tenant_id, provider="google_drive", auth_type="oauth2", status="active"))
    db.mcp_tools.append(TenantMCPTool(id=uuid.uuid4(), tenant_id=tenant_id, server_id=uuid.uuid4(), tool_name="drive_fake", display_name="drive_fake", description="fake", is_enabled=True))

    payload = _client(db, tenant_id).get("/api/mcp/tools").json()

    expected = {
        "google_drive_list_files",
        "google_drive_search_files",
        "google_drive_read_file",
        "google_drive_create_document",
        "google_drive_create_folder",
    }
    ids = {item["id"] for item in payload}
    assert expected.issubset(ids)
    google_tool = next(item for item in payload if item["id"] == "google_drive_list_files")
    assert google_tool["display_name"] == "[Google Drive] Listar arquivos"
    assert google_tool["server_name"] == "Google Drive conectado"
    assert google_tool["metadata"]["provider"] == "google_drive"
    assert any(item["tool_name"] == "drive_fake" and item["id"] != "google_drive_list_files" for item in payload)


def test_unconnected_tenant_does_not_see_google_drive_tools(monkeypatch):
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", "integration-test-secret")
    tenant_id = uuid.uuid4()
    payload = _client(FakeDb(), tenant_id).get("/api/mcp/tools").json()
    assert all(not str(item["id"]).startswith("google_drive_") for item in payload)
