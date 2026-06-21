from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tenant import Tenant
from app.schemas.integration_connection import IntegrationConnectionStatusOut
from app.services.integration_connection_service import IntegrationConnectionService
from app.services.suitable_service import PROVIDER
from app.services.tenant_service import get_current_tenant

router = APIRouter(prefix="/api/integrations/suitable", tags=["integrations"])


class SuitableConnectIn(BaseModel):
    api_key: str = Field(min_length=1)
    metadata: dict[str, Any] | None = None


@router.get("/status", response_model=IntegrationConnectionStatusOut)
def suitable_status(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    service = IntegrationConnectionService(db)
    return service.to_public_status(service.get_connection(tenant.id, PROVIDER), PROVIDER)


@router.post("/connect", response_model=IntegrationConnectionStatusOut)
def suitable_connect(payload: SuitableConnectIn, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    service = IntegrationConnectionService(db)
    conn = service.upsert_connection(tenant_id=tenant.id, provider=PROVIDER, auth_type="api_key", api_key=payload.api_key, metadata=payload.metadata or {}, status="active")
    return service.to_public_status(conn, PROVIDER)


@router.delete("/disconnect", response_model=IntegrationConnectionStatusOut)
def suitable_disconnect(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    service = IntegrationConnectionService(db)
    conn = service.disconnect_connection(tenant.id, PROVIDER)
    return service.to_public_status(conn, PROVIDER)
