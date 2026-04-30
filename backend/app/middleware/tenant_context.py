from __future__ import annotations

import uuid

from fastapi import Request
from starlette import status
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.core.tenant import set_current_tenant_id

PUBLIC_PATHS = ("/health", "/docs", "/openapi.json", "/redoc")


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
        path = request.url.path
        if path.startswith(PUBLIC_PATHS):
            return await call_next(request)

        tenant_header = (request.headers.get("x-tenant-id") or "").strip()
        tenant_query = (request.query_params.get("tenant") or "").strip()
        tenant_subdomain = _resolve_tenant_from_host(request.headers.get("host", ""))
        tenant_value = tenant_header or tenant_query or tenant_subdomain

        if not tenant_value:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": "Tenant is required"},
            )
        try:
            tenant_id = uuid.UUID(tenant_value)
        except ValueError:
            return JSONResponse(
                status_code=status.HTTP_400_BAD_REQUEST,
                content={"detail": "Tenant is invalid"},
            )

        request.state.tenant_id = tenant_id
        set_current_tenant_id(tenant_id)
        try:
            response = await call_next(request)
            return response
        finally:
            set_current_tenant_id(None)
