from __future__ import annotations

import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.tenant import set_current_tenant_id

PUBLIC_PATHS = (
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/register",
    "/api/login",
)


def _resolve_tenant_from_host(host: str) -> str:
    host_without_port = host.split(":", 1)[0].strip().lower()
    if not host_without_port:
        return ""

    parts = host_without_port.split(".")
    if len(parts) < 3:
        return ""

    subdomain = parts[0].strip()
    if subdomain in {"www"}:
        return ""

    return subdomain


class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        print("PATH:", request.url.path)
        print("METHOD:", request.method)
        print("TENANT HEADER:", request.headers.get("X-Tenant-ID"))

        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if path in PUBLIC_PATHS:
            return await call_next(request)

        tenant_header = (request.headers.get("x-tenant-id") or "").strip()
        if not tenant_header:
            return JSONResponse(status_code=400, content={"detail": "Tenant obrigatório"})

        tenant_query = (request.query_params.get("tenant") or "").strip()
        tenant_subdomain = _resolve_tenant_from_host(request.headers.get("host", ""))
        tenant_value = tenant_header or tenant_query or tenant_subdomain

        tenant_id = None
        try:
            tenant_id = uuid.UUID(tenant_value)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "Tenant obrigatório"})

        request.state.tenant_id = tenant_id
        set_current_tenant_id(tenant_id)
        try:
            response = await call_next(request)
            return response
        finally:
            set_current_tenant_id(None)
