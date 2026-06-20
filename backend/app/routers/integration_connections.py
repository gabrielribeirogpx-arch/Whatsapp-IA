from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tenant import Tenant
from app.schemas.integration_connection import IntegrationConnectionStatusOut
from app.services.integration_connection_service import IntegrationConnectionService
from app.services.tenant_service import get_current_tenant

router = APIRouter(prefix="/integrations/connections", tags=["integration-connections"])


@router.get("", response_model=list[IntegrationConnectionStatusOut])
def list_connections(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    service = IntegrationConnectionService(db)
    return [service.to_public_status(connection) for connection in service.list_connections(tenant.id)]


@router.get("/{provider}/status", response_model=IntegrationConnectionStatusOut)
def get_connection_status(provider: str, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    service = IntegrationConnectionService(db)
    return service.to_public_status(service.get_connection(tenant.id, provider), provider=provider)


@router.delete("/{provider}", response_model=IntegrationConnectionStatusOut)
def disconnect_connection(provider: str, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    service = IntegrationConnectionService(db)
    connection = service.disconnect_connection(tenant.id, provider)
    return service.to_public_status(connection, provider=provider)
