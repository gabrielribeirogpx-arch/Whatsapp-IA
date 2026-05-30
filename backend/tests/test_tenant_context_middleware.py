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
