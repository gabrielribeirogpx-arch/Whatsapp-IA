from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.tenant_context import TenantContextMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(TenantContextMiddleware)

    @app.post("/api/admin/multi-tenant-investigation")
    def investigation_stub():
        return {"ok": True}

    @app.get("/api/protected")
    def protected_stub():
        return {"ok": True}

    @app.get("/api/integrations/google-calendar/connect")
    def google_calendar_connect_stub():
        return {"entered": True}

    @app.get("/api/integrations/google-calendar/callback")
    def google_calendar_callback_stub():
        return {"entered": True}

    @app.get("/api/integrations/google-sheets/connect-url")
    def google_sheets_connect_url_stub():
        return {"entered": True}

    @app.get("/api/integrations/google-sheets/callback")
    def google_sheets_callback_stub():
        return {"entered": True}

    return app


def test_multi_tenant_investigation_bypasses_tenant_header_requirement():
    client = TestClient(_build_app())

    response = client.post("/api/admin/multi-tenant-investigation")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_other_protected_routes_still_require_tenant_header():
    client = TestClient(_build_app())

    response = client.get("/api/protected")

    assert response.status_code == 400
    assert response.json() == {"detail": "X-Tenant-ID é obrigatório"}


def test_google_calendar_connect_bypasses_tenant_header_requirement():
    client = TestClient(_build_app())

    response = client.get("/api/integrations/google-calendar/connect?tenant_slug=gabriel-ribeiro")

    assert response.status_code == 200
    assert response.json() == {"entered": True}


def test_google_calendar_callback_bypasses_tenant_header_requirement():
    client = TestClient(_build_app())

    response = client.get("/api/integrations/google-calendar/callback")

    assert response.status_code == 200
    assert response.json() == {"entered": True}


def test_google_sheets_connect_url_bypasses_tenant_header_requirement():
    client = TestClient(_build_app())

    response = client.get("/api/integrations/google-sheets/connect-url?tenant_slug=gabriel-ribeiro")

    assert response.status_code == 200
    assert response.json() == {"entered": True}


def test_google_sheets_callback_bypasses_tenant_header_requirement():
    client = TestClient(_build_app())

    response = client.get("/api/integrations/google-sheets/callback")

    assert response.status_code == 200
    assert response.json() == {"entered": True}
