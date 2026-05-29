from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.testclient import TestClient

from app.database import get_db
from app.main import REQUIRED_CORS_ORIGINS, _parse_allowed_origins, preflight_handler
from app.routers import flows


class _DummyDb:
    pass


def _override_get_db():
    yield _DummyDb()


def _build_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[*REQUIRED_CORS_ORIGINS, "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.options("/{full_path:path}")(preflight_handler)
    app.include_router(flows.router, prefix="/api/flows")
    app.include_router(flows.crud_router, prefix="/api/flows")
    app.dependency_overrides[get_db] = _override_get_db
    return app


def test_preflight_allows_tenant_header():
    client = TestClient(_build_test_app())
    response = client.options(
        "/api/flows",
        headers={
            "Origin": "http://localhost:3000",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Tenant-ID, Content-Type",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "GET" in response.headers.get("access-control-allow-methods", "")
    allow_headers = response.headers.get("access-control-allow-headers", "")
    assert "X-Tenant-ID" in allow_headers or "*" in allow_headers


def test_preflight_allows_railway_frontend_origin():
    client = TestClient(_build_test_app())
    origin = "https://frontend-whatsapp-ia-production.up.railway.app"
    response = client.options(
        "/api/flows",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "X-Tenant-ID, Content-Type",
        },
    )

    assert response.status_code == 200
    assert response.headers.get("access-control-allow-origin") == origin
    assert "GET" in response.headers.get("access-control-allow-methods", "")
    allow_headers = response.headers.get("access-control-allow-headers", "")
    assert "X-Tenant-ID" in allow_headers or "*" in allow_headers


def test_required_cors_origins_are_kept_when_env_overrides_defaults(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "https://custom.example.com")

    parsed = _parse_allowed_origins()

    assert parsed == [
        "https://custom.example.com",
        "https://frontend-whatsapp-ia-production.up.railway.app",
        "https://whatsapp-ia-nine.vercel.app",
    ]


def test_missing_tenant_header_returns_403_on_sensitive_reads_and_writes():
    client = TestClient(_build_test_app())

    read_response = client.get("/api/flows")
    write_response = client.post("/api/flows", json={"name": "f", "nodes": [], "edges": []})

    assert read_response.status_code == 403
    assert read_response.json() == {"detail": "X-Tenant-ID header is required"}

    assert write_response.status_code == 403
    assert write_response.json() == {"detail": "X-Tenant-ID header is required"}
