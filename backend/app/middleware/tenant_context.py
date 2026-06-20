from __future__ import annotations

import uuid

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.tenant import set_current_tenant_id

PUBLIC_PATHS = (
    "/",
    "/health",
    "/docs",
    "/openapi.json",
    "/redoc",
    "/api/register",
    "/api/login",
    "/api/forgot-password",
    "/api/reset-password",
    "/api/integrations/google-calendar/connect",
    "/api/integrations/google-calendar/callback",
    "/webhook",
    "/api/webhook",
    "/uploads",
)


GLOBAL_READONLY_PATHS = (
    "/api/admin/multi-tenant-investigation",
    "/api/debug/runtime-flow",
)

SSE_QUERY_TENANT_PATH_PREFIXES = (
    "/api/sse/",
    "/api/stream/",
    "/api/dashboard/stream",
    "/api/crm/contacts/",
)


def _is_public_path(path: str) -> bool:
    for public_path in PUBLIC_PATHS:
        if path == public_path or path.startswith(f"{public_path}/"):
            return True
    return False


def _is_global_readonly_path(path: str) -> bool:
    return path in GLOBAL_READONLY_PATHS


def _allows_sse_query_tenant(path: str) -> bool:
    if path.startswith("/api/sse/") or path.startswith("/api/stream/"):
        return True
    return any(path.startswith(prefix) for prefix in SSE_QUERY_TENANT_PATH_PREFIXES) and path.endswith("stream")


class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if _is_public_path(path):
            return await call_next(request)

        if _is_global_readonly_path(path):
            set_current_tenant_id(None)
            try:
                return await call_next(request)
            finally:
                set_current_tenant_id(None)

        tenant_header = (request.headers.get("x-tenant-id") or "").strip()
        if not tenant_header and _allows_sse_query_tenant(path):
            tenant_header = (request.query_params.get("tenant_id") or "").strip()
        if not tenant_header:
            return JSONResponse(status_code=400, content={"detail": "X-Tenant-ID é obrigatório"})

        try:
            tenant_id = uuid.UUID(tenant_header)
        except ValueError:
            return JSONResponse(status_code=400, content={"detail": "X-Tenant-ID inválido"})

        request.state.tenant_id = tenant_id
        set_current_tenant_id(tenant_id)
        try:
            response = await call_next(request)
            return response
        finally:
            set_current_tenant_id(None)
