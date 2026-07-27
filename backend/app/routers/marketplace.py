from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import MarketplaceInstallation, Tenant, TenantUser
from app.routers.account import get_current_user
from app.services.marketplace_installation_service import MarketplaceInstallationService
from app.services.tenant_service import get_current_tenant

router = APIRouter(prefix="/marketplace", tags=["marketplace"])
class InstallBody(BaseModel):
    variant: str = "Sem IA"
def service(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(get_current_user)):
    return MarketplaceInstallationService(db, tenant, user)
def output(item):
    return {"id": str(item.id), "template_slug": item.template_slug, "template_version": item.template_version, "variant": item.variant, "status": item.status, "installed_by_user_id": str(item.installed_by_user_id), "started_at": item.started_at, "completed_at": item.completed_at, "error": {"code": item.error_code, "summary": item.error_summary} if item.error_code else None, "created_resources": item.created_resources, "dependencies": item.dependency_snapshot, "checklist": item.customization_state.get("checklist", []), "resources": [{"type": r.resource_type, "id": r.resource_id, "name": r.resource_name, "creation_status": r.creation_status, "rollback_status": r.rollback_status, "metadata": r.metadata_json} for r in item.resources]}
def translate(exc):
    if isinstance(exc, PermissionError): raise HTTPException(403, str(exc))
    if isinstance(exc, LookupError): raise HTTPException(404, str(exc))
    if isinstance(exc, ValueError): raise HTTPException(422, str(exc))
    raise exc
@router.get("/items/{slug}/installation-preview")
def preview(slug: str, variant: str = Query("Sem IA"), svc=Depends(service)):
    try: return svc.preview(slug, variant)
    except Exception as exc: translate(exc)
@router.post("/items/{slug}/install")
def install(slug: str, body: InstallBody, idempotency_key: str = Header(alias="Idempotency-Key", min_length=8, max_length=255), svc=Depends(service)):
    try: return output(svc.install(slug, body.variant, idempotency_key))
    except Exception as exc: translate(exc)
@router.get("/installations")
def installations(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(get_current_user)):
    return [output(x) for x in db.scalars(select(MarketplaceInstallation).where(MarketplaceInstallation.tenant_id == tenant.id).order_by(MarketplaceInstallation.created_at.desc())).unique().all()]
def owned(installation_id, db, tenant):
    item = db.scalar(select(MarketplaceInstallation).where(MarketplaceInstallation.id == installation_id, MarketplaceInstallation.tenant_id == tenant.id))
    if not item: raise HTTPException(404, "installation_not_found")
    return item
@router.get("/installations/{installation_id}")
def detail(installation_id: UUID, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(get_current_user)):
    return output(owned(installation_id, db, tenant))
@router.post("/installations/{installation_id}/retry")
def retry(installation_id: UUID, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), svc=Depends(service)):
    item = owned(installation_id, db, tenant); svc._event("template_install_retried", item); db.commit(); return output(item)
@router.post("/installations/{installation_id}/rollback")
def rollback(installation_id: UUID, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), svc=Depends(service)):
    return output(svc.rollback(owned(installation_id, db, tenant)))
