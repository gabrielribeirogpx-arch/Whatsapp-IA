from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tenant import Tenant
from app.models.user import TenantUser
from app.routers.account import get_current_user
from app.security.workspace_rbac import WorkspacePermission
from app.services.administrative_audit import require_administrative_permission
from app.services.audit_service import write_audit_log
from app.schemas.integration_connection import IntegrationConnectionStatusOut
from app.services.integration_connection_service import GOOGLE_CONNECTION_PROVIDERS, IntegrationConnectionService, is_google_auth_error
from app.services.gmail_service import GmailService
from app.services.google_calendar_service import GoogleCalendarService
from app.services.google_drive_service import GoogleDriveService
from app.services.google_sheets_service import GoogleSheetsService
from app.services.tenant_service import get_current_tenant

router = APIRouter(prefix="/integrations/connections", tags=["integration-connections"])


def validate_google_connection_status(db: Session, tenant_id, provider: str):
    service = IntegrationConnectionService(db)
    provider = service.normalize_provider(provider)
    connection = service.get_connection(tenant_id, provider)
    if connection is None or connection.status != "active":
        return connection
    validators = {
        "google_calendar": GoogleCalendarService,
        "google_drive": GoogleDriveService,
        "google_sheets": GoogleSheetsService,
        "gmail": GmailService,
    }
    validator_cls = validators.get(provider)
    if validator_cls is None:
        return connection
    try:
        result = validator_cls(db, tenant_id).refresh_access_token_if_needed(force=True)
    except Exception:
        return connection
    if result.get("ok") is False and is_google_auth_error(result.get("status_code"), result, result.get("message")):
        connection = service.mark_google_connection_revoked(tenant_id, provider)
    return connection or service.get_connection(tenant_id, provider)


@router.get("", response_model=list[IntegrationConnectionStatusOut])
def list_connections(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    service = IntegrationConnectionService(db)
    return [service.to_public_status(connection) for connection in service.list_connections(tenant.id)]


@router.get("/{provider}/status", response_model=IntegrationConnectionStatusOut)
def get_connection_status(provider: str, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    service = IntegrationConnectionService(db)
    normalized_provider = service.normalize_provider(provider)
    connection = validate_google_connection_status(db, tenant.id, normalized_provider) if normalized_provider in GOOGLE_CONNECTION_PROVIDERS else service.get_connection(tenant.id, normalized_provider)
    return service.to_public_status(connection, provider=normalized_provider)


@router.delete("/{provider}", response_model=IntegrationConnectionStatusOut)
def disconnect_connection(provider: str, request: Request, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), user: TenantUser = Depends(get_current_user)):
    require_administrative_permission(db, user, WorkspacePermission.MANAGE_INTEGRATIONS, request=request, action="integration_disconnected", resource_type="integration", resource_id=provider)
    service = IntegrationConnectionService(db)
    normalized_provider = service.normalize_provider(provider)
    if normalized_provider == "google":
        rows = service.disconnect_google_connections(tenant.id, commit=False)
        write_audit_log(db, action="integration_disconnected", tenant_id=tenant.id, user_id=user.id, entity_type="integration", entity_id="google", metadata={"provider": "google", "old_status": "active", "new_status": "disconnected", "connections_changed": len(rows)}, request=request)
        db.commit()
        connection = service.get_connection(tenant.id, "google")
        return service.to_public_status(connection, provider="google")
    connection = service.disconnect_connection(tenant.id, normalized_provider, commit=False)
    write_audit_log(db, action="integration_disconnected", tenant_id=tenant.id, user_id=user.id, entity_type="integration", entity_id=getattr(connection, "id", normalized_provider), metadata={"provider": normalized_provider, "old_status": getattr(connection, "status", None) and "active", "new_status": "disconnected"}, request=request)
    db.commit()
    return service.to_public_status(connection, provider=normalized_provider)
