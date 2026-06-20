from __future__ import annotations

import uuid
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models.tenant import Tenant
from app.routers import google_calendar_integration as router_module
from app.routers.google_calendar_integration import (
    PROVIDER,
    create_oauth_state,
    get_google_calendar_connect_tenant,
    router,
    verify_oauth_state,
)
from app.services.integration_connection_service import IntegrationConnectionService
from app.services.tenant_service import get_current_tenant
from tests.test_integration_connection_service import FakeDb


@pytest.fixture(autouse=True)
def oauth_env(monkeypatch):
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", "integration-test-secret")
    monkeypatch.setenv("GOOGLE_CALENDAR_STATE_SECRET", "state-secret")
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GOOGLE_CALENDAR_REDIRECT_URI", "https://app.example.com/api/integrations/google-calendar/callback")


def _client(tenant_id: uuid.UUID, db: FakeDb) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_current_tenant] = lambda: SimpleNamespace(id=tenant_id)
    app.dependency_overrides[get_google_calendar_connect_tenant] = lambda: SimpleNamespace(id=tenant_id)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


class TenantFakeDb(FakeDb):
    def __init__(self, tenants):
        super().__init__()
        self.tenants = list(tenants)

    def execute(self, statement):
        compiled = statement.compile()
        params = compiled.params
        if "slug_1" in params:
            rows = [tenant for tenant in self.tenants if tenant.slug == params["slug_1"]]
            return _ExecuteResult(rows)
        return super().execute(statement)


def _tenant_client(db) -> TestClient:
    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows

    def first(self):
        return self._rows[0] if self._rows else None


class _ExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _ScalarResult(self._rows)


def test_google_calendar_state_contains_tenant_nonce_and_rejects_tampering():
    tenant_id = uuid.uuid4()
    state = create_oauth_state(tenant_id, nonce="nonce-123")

    payload = verify_oauth_state(state)

    assert payload["tenant_id"] == str(tenant_id)
    assert payload["nonce"] == "nonce-123"
    with pytest.raises(Exception):
        verify_oauth_state(state + "tampered")


def test_connect_redirect_includes_secure_state_and_required_scopes():
    tenant_id = uuid.uuid4()
    response = _client(tenant_id, FakeDb()).get("/api/integrations/google-calendar/connect", follow_redirects=False)

    assert response.status_code == 302
    parsed = urlparse(response.headers["location"])
    params = parse_qs(parsed.query)
    assert parsed.netloc == "accounts.google.com"
    assert verify_oauth_state(params["state"][0])["tenant_id"] == str(tenant_id)
    for scope in router_module.SCOPES:
        assert scope in params["scope"][0].split()


def _assert_connect_redirect_for_tenant(response, tenant_id: uuid.UUID):
    assert response.status_code == 302
    params = parse_qs(urlparse(response.headers["location"]).query)
    assert verify_oauth_state(params["state"][0])["tenant_id"] == str(tenant_id)


def test_connect_resolves_valid_tenant_slug(monkeypatch, caplog):
    caplog.set_level("INFO")
    tenant_id = uuid.uuid4()
    tenant = Tenant(id=tenant_id, name="Tenant", slug="tenant-ok")
    response = _tenant_client(TenantFakeDb([tenant])).get(
        "/api/integrations/google-calendar/connect?tenant_slug=tenant-ok",
        follow_redirects=False,
    )

    _assert_connect_redirect_for_tenant(response, tenant_id)
    assert "source=query slug" in caplog.text


def test_connect_resolves_valid_tenant_id(monkeypatch, caplog):
    caplog.set_level("INFO")
    tenant_id = uuid.uuid4()
    tenant = Tenant(id=tenant_id, name="Tenant", slug="tenant-ok")
    monkeypatch.setattr(
        "app.services.tenant_service.get_tenant_cached",
        lambda _db, parsed: tenant if parsed == tenant_id else None,
    )

    response = _tenant_client(TenantFakeDb([tenant])).get(
        f"/api/integrations/google-calendar/connect?tenant_id={tenant_id}",
        follow_redirects=False,
    )

    _assert_connect_redirect_for_tenant(response, tenant_id)
    assert "source=query id" in caplog.text


def test_connect_resolves_x_tenant_slug_header(caplog):
    caplog.set_level("INFO")
    tenant_id = uuid.uuid4()
    tenant = Tenant(id=tenant_id, name="Tenant", slug="tenant-ok")

    response = _tenant_client(TenantFakeDb([tenant])).get(
        "/api/integrations/google-calendar/connect",
        headers={"X-Tenant-Slug": "tenant-ok"},
        follow_redirects=False,
    )

    _assert_connect_redirect_for_tenant(response, tenant_id)
    assert "source=header X-Tenant-Slug" in caplog.text


def test_connect_resolves_x_tenant_id_header(monkeypatch, caplog):
    caplog.set_level("INFO")
    tenant_id = uuid.uuid4()
    tenant = Tenant(id=tenant_id, name="Tenant", slug="tenant-ok")
    monkeypatch.setattr(
        "app.services.tenant_service.get_tenant_cached",
        lambda _db, parsed: tenant if parsed == tenant_id else None,
    )

    response = _tenant_client(TenantFakeDb([tenant])).get(
        "/api/integrations/google-calendar/connect",
        headers={"X-Tenant-Id": str(tenant_id)},
        follow_redirects=False,
    )

    _assert_connect_redirect_for_tenant(response, tenant_id)
    assert "source=header X-Tenant-Id" in caplog.text


def test_connect_resolves_x_tenant_id_uppercase_header(monkeypatch, caplog):
    caplog.set_level("INFO")
    tenant_id = uuid.uuid4()
    tenant = Tenant(id=tenant_id, name="Tenant", slug="tenant-ok")
    monkeypatch.setattr(
        "app.services.tenant_service.get_tenant_cached",
        lambda _db, parsed: tenant if parsed == tenant_id else None,
    )

    response = _tenant_client(TenantFakeDb([tenant])).get(
        "/api/integrations/google-calendar/connect",
        headers={"X-Tenant-ID": str(tenant_id)},
        follow_redirects=False,
    )

    _assert_connect_redirect_for_tenant(response, tenant_id)
    assert "source=header" in caplog.text


def test_connect_without_tenant_returns_tenant_not_identified():
    response = _tenant_client(TenantFakeDb([])).get(
        "/api/integrations/google-calendar/connect",
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Tenant não identificado"}


def test_status_and_disconnect_use_integration_connections_without_exposing_tokens():
    tenant_id = uuid.uuid4()
    db = FakeDb()
    IntegrationConnectionService(db).upsert_connection(
        tenant_id=tenant_id,
        provider=PROVIDER,
        auth_type="oauth2",
        access_token="access-secret",
        refresh_token="refresh-secret",
        scopes=["openid"],
        metadata={"account_email": "user@example.com"},
    )
    client = _client(tenant_id, db)

    status = client.get("/api/integrations/google-calendar/status")
    disconnected = client.delete("/api/integrations/google-calendar/disconnect")

    assert status.status_code == 200
    assert status.json()["connected"] is True
    assert status.json()["auth_type"] == "oauth2"
    assert status.json()["metadata"] == {"account_email": "user@example.com"}
    assert "access-secret" not in status.text
    assert "refresh-secret" not in status.text
    assert disconnected.status_code == 200
    assert disconnected.json()["connected"] is False


def test_callback_exchanges_code_fetches_email_and_persists_encrypted_tokens(monkeypatch):
    tenant_id = uuid.uuid4()
    db = FakeDb()
    state = create_oauth_state(tenant_id, nonce="callback-nonce")

    class Response:
        def __init__(self, payload, status_code=200):
            self._payload = payload
            self.status_code = status_code

        def json(self):
            return self._payload

    def fake_post(url, data, timeout):
        assert url == router_module.TOKEN_URL
        assert data["code"] == "auth-code"
        assert data["grant_type"] == "authorization_code"
        return Response({"access_token": "access-token", "refresh_token": "refresh-token", "expires_in": 3600, "scope": "openid email profile"})

    def fake_get(url, headers, timeout):
        assert url == router_module.USERINFO_URL
        assert headers["Authorization"] == "Bearer access-token"
        return Response({"email": "calendar@example.com"})

    monkeypatch.setattr(router_module.requests, "post", fake_post)
    monkeypatch.setattr(router_module.requests, "get", fake_get)

    response = _client(tenant_id, db).get(f"/api/integrations/google-calendar/callback?code=auth-code&state={state}")

    assert response.status_code == 200
    assert response.json() == {"provider": PROVIDER, "connected": True, "account_email": "calendar@example.com"}
    connection = db.connections[0]
    assert connection.provider == PROVIDER
    assert connection.auth_type == "oauth2"
    assert connection.metadata_json == {"account_email": "calendar@example.com"}
    assert connection.access_token_encrypted != "access-token"
    assert connection.refresh_token_encrypted != "refresh-token"
    assert IntegrationConnectionService.decrypt_credential(connection.access_token_encrypted) == "access-token"
    assert IntegrationConnectionService.decrypt_credential(connection.refresh_token_encrypted) == "refresh-token"
    assert "access-token" not in response.text
    assert "refresh-token" not in response.text
