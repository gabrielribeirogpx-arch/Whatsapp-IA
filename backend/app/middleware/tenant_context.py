from __future__ import annotations

import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware


class TenantContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        tenant_header = (request.headers.get("x-tenant-id") or "").strip()
        request.state.tenant_id = None

        if tenant_header:
            try:
                request.state.tenant_id = uuid.UUID(tenant_header)
            except ValueError:
                request.state.tenant_id = None

        response = await call_next(request)
        return response
