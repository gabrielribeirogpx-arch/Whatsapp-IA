from __future__ import annotations

import uuid

from fastapi import HTTPException
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.security import decode_tenant_token


PROTECTED_PREFIXES = ("/api/flows", "/api/runtime")


class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        tenant_header = (request.headers.get("x-tenant-id") or "").strip()
        auth_header = (request.headers.get("authorization") or "").strip()
        request.state.tenant_id = None
        request.state.tenant_slug = None

        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            payload = decode_tenant_token(token)
            tenant_id = str(payload.get("tenant_id") or payload.get("sub") or "").strip()
            if not tenant_id:
                raise HTTPException(status_code=401, detail="Token sem tenant_id")
            try:
                request.state.tenant_id = uuid.UUID(tenant_id)
            except ValueError as exc:
                raise HTTPException(status_code=401, detail="tenant_id inválido no token") from exc
            request.state.tenant_slug = str(payload.get("slug") or "").strip() or None

        if tenant_header:
            try:
                header_tenant_id = uuid.UUID(tenant_header)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail="X-Tenant-ID header is invalid") from exc
            if request.state.tenant_id and request.state.tenant_id != header_tenant_id:
                raise HTTPException(status_code=403, detail="Cross-tenant access denied")
            request.state.tenant_id = header_tenant_id

        if request.url.path.startswith(PROTECTED_PREFIXES) and request.state.tenant_id is None:
            raise HTTPException(status_code=401, detail="Authorization token is required")

        response = await call_next(request)
        return response
