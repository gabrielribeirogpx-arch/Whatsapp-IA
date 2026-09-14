from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tenant import Tenant
from app.models.user import TenantUser
from app.routers.account import get_current_user
from app.security.workspace_rbac import WorkspacePermission
from app.schemas.integration_connection import IntegrationConnectionStatusOut
from app.services.integration_connection_service import IntegrationConnectionService
from app.services.administrative_audit import require_administrative_permission
from app.services.audit_service import write_audit_log
from app.services.suitable_service import PROVIDER, SuitableService
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
def suitable_connect(payload: SuitableConnectIn, request: Request, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), user: TenantUser = Depends(get_current_user)):
    require_administrative_permission(db, user, WorkspacePermission.MANAGE_INTEGRATIONS, request=request, action="integration_connected", resource_type="integration", resource_id=PROVIDER)
    service = IntegrationConnectionService(db)
    conn = service.upsert_connection(tenant_id=tenant.id, provider=PROVIDER, auth_type="api_key", api_key=payload.api_key, metadata=payload.metadata or {}, status="active", commit=False)
    db.flush()
    write_audit_log(db, action="integration_connected", tenant_id=tenant.id, user_id=user.id, entity_type="integration", entity_id=conn.id, metadata={"provider": PROVIDER, "auth_type": "api_key"}, request=request)
    db.commit()
    return service.to_public_status(conn, PROVIDER)


@router.post("/disconnect", response_model=IntegrationConnectionStatusOut)
def suitable_disconnect(request: Request, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), user: TenantUser = Depends(get_current_user)):
    require_administrative_permission(db, user, WorkspacePermission.MANAGE_INTEGRATIONS, request=request, action="integration_disconnected", resource_type="integration", resource_id=PROVIDER)
    service = IntegrationConnectionService(db)
    conn = service.disconnect_connection(tenant.id, PROVIDER, commit=False)
    db.flush()
    write_audit_log(db, action="integration_disconnected", tenant_id=tenant.id, user_id=user.id, entity_type="integration", entity_id=getattr(conn, "id", PROVIDER), metadata={"provider": PROVIDER, "new_status": "disconnected"}, request=request)
    db.commit()
    return service.to_public_status(conn, PROVIDER)


@router.delete("/disconnect", response_model=IntegrationConnectionStatusOut)
def suitable_disconnect_delete(request: Request, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), user: TenantUser = Depends(get_current_user)):
    return suitable_disconnect(request, tenant, db, user)


@router.post("/check-key")
def suitable_check_key(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    result = SuitableService(db, tenant.id).check_key()
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result)
    return result
