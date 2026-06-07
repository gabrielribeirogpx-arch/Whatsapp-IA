from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.runtime_flow_diagnostics import build_runtime_flow_diagnostic

router = APIRouter(prefix="/api/debug", tags=["runtime-flow-debug"])


@router.get("/runtime-flow")
def runtime_flow_diagnostic(
    builder_tenant: str | None = Query(default=None),
    phone_number_id: str | None = Query(default=None),
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    builder_tenant_id = builder_tenant or x_tenant_id
    # Validate early when a non-empty tenant is provided so the endpoint returns a clear 422.
    if builder_tenant_id:
        try:
            uuid.UUID(str(builder_tenant_id))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="builder_tenant inválido") from exc
    return build_runtime_flow_diagnostic(
        db,
        builder_tenant_id=builder_tenant_id,
        phone_number_id=phone_number_id,
    ).as_dict()
