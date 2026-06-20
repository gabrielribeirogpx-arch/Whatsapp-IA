from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.integration_connection import IntegrationConnection
from app.routers.integration_connections import router
from app.services.integration_connection_service import IntegrationConnectionService
from app.services.tenant_service import get_current_tenant
from app.database import get_db


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
        self.connections: list[IntegrationConnection] = []
        self.commits = 0

    def add(self, connection):
        if connection not in self.connections:
            self.connections.append(connection)

    def commit(self):
        self.commits += 1

    def refresh(self, connection):
        if connection.id is None:
            connection.id = uuid.uuid4()

    def execute(self, statement):
        compiled = statement.compile()
        params = compiled.params
        rows = list(self.connections)
        tenant_id = params.get("tenant_id_1")
        provider = params.get("provider_1")
        if tenant_id is not None:
            rows = [row for row in rows if row.tenant_id == tenant_id]
        if provider is not None:
            rows = [row for row in rows if row.provider == provider]
        rows.sort(key=lambda row: row.provider)
        return _ExecuteResult(rows)


@pytest.fixture(autouse=True)
def encryption_key(monkeypatch):
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", "integration-test-secret")


def test_encrypts_and_decrypts_credentials():
    encrypted = IntegrationConnectionService.encrypt_credential("secret-token")

    assert encrypted is not None
    assert encrypted.startswith("oauth:v1:")
    assert "secret-token" not in encrypted
    assert IntegrationConnectionService.decrypt_credential(encrypted) == "secret-token"


def test_upsert_creates_and_updates_existing_connection():
    tenant_id = uuid.uuid4()
    db = FakeDb()
    service = IntegrationConnectionService(db)  # type: ignore[arg-type]

    first = service.upsert_connection(
        tenant_id=tenant_id,
        provider="HubSpot",
        auth_type="oauth",
        access_token="access-1",
        refresh_token="refresh-1",
        scopes=["contacts.read"],
        metadata={"account": "A"},
    )
    second = service.upsert_connection(
        tenant_id=tenant_id,
        provider="hubspot",
        auth_type="oauth",
        access_token="access-2",
        scopes=["contacts.write"],
        metadata={"account": "B"},
    )

    assert first is second
    assert len(db.connections) == 1
    assert second.provider == "hubspot"
    assert second.scopes == ["contacts.write"]
    assert second.metadata_json == {"account": "B"}
    assert IntegrationConnectionService.decrypt_credential(second.access_token_encrypted) == "access-2"
    assert IntegrationConnectionService.decrypt_credential(second.refresh_token_encrypted) == "refresh-1"
    assert db.commits == 2


def test_public_status_does_not_include_decrypted_or_encrypted_tokens():
    tenant_id = uuid.uuid4()
    expires_at = datetime.utcnow() + timedelta(hours=1)
    connection = IntegrationConnection(
        tenant_id=tenant_id,
        provider="stripe",
        auth_type="api_key",
        api_key_encrypted=IntegrationConnectionService.encrypt_credential("sk_live_secret"),
        status="active",
        scopes=["payments"],
        metadata_json={"mode": "live"},
        expires_at=expires_at,
    )

    payload = IntegrationConnectionService.to_public_status(connection)

    assert payload == {
        "provider": "stripe",
        "auth_type": "api_key",
        "status": "active",
        "connected": True,
        "scopes": ["payments"],
        "metadata": {"mode": "live"},
        "expires_at": expires_at,
    }
    assert "token" not in payload
    assert "api_key" not in payload
    assert "sk_live_secret" not in str(payload)


def test_disconnect_clears_credentials_and_marks_connection_disconnected():
    tenant_id = uuid.uuid4()
    db = FakeDb()
    service = IntegrationConnectionService(db)  # type: ignore[arg-type]
    service.upsert_connection(
        tenant_id=tenant_id,
        provider="slack",
        auth_type="oauth",
        access_token="access",
        refresh_token="refresh",
        expires_at=datetime.utcnow() + timedelta(hours=1),
    )

    connection = service.disconnect_connection(tenant_id, "slack")

    assert connection is not None
    assert connection.status == "disconnected"
    assert connection.access_token_encrypted is None
    assert connection.refresh_token_encrypted is None
    assert connection.api_key_encrypted is None
    assert connection.expires_at is None
    assert service.is_connected(tenant_id, "slack") is False


def test_status_endpoint_returns_public_payload_without_tokens():
    tenant_id = uuid.uuid4()
    db = FakeDb()
    service = IntegrationConnectionService(db)  # type: ignore[arg-type]
    service.upsert_connection(
        tenant_id=tenant_id,
        provider="notion",
        auth_type="api_key",
        api_key="secret-api-key",
        scopes=["pages.read"],
        metadata={"workspace": "Wazza"},
    )
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_current_tenant] = lambda: SimpleNamespace(id=tenant_id)
    app.dependency_overrides[get_db] = lambda: db

    response = TestClient(app).get("/api/integrations/connections/notion/status")

    assert response.status_code == 200
    assert response.json() == {
        "provider": "notion",
        "auth_type": "api_key",
        "status": "active",
        "connected": True,
        "scopes": ["pages.read"],
        "metadata": {"workspace": "Wazza"},
        "expires_at": None,
    }
    assert "secret-api-key" not in response.text
    assert "api_key" not in response.text
