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


class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)

        path = request.url.path
        if any(path.startswith(public_path) for public_path in PUBLIC_PATHS):
            return await call_next(request)

        tenant_header = (request.headers.get("x-tenant-id") or "").strip()
        if not tenant_header:
            return JSONResponse(status_code=403, content={"detail": "X-Tenant-ID é obrigatório"})

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
