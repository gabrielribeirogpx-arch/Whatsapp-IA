from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import MarketplaceInstallation, MarketplaceTemplate, MarketplaceTemplateVersion, Tenant, TenantUser
from app.services.official_marketplace_template_service import OfficialMarketplaceTemplateService
from app.routers.account import get_current_user
from app.services.marketplace_installation_service import MarketplaceInstallationService
from app.marketplace_assets import ASSETS, ITEMS, MarketplaceGraphValidator
from app.services.tenant_service import get_current_tenant

router = APIRouter(prefix="/marketplace", tags=["marketplace"])
class InstallBody(BaseModel):
    variant: str = "Sem IA"
class ComposerDraft(BaseModel):
    key: str
    template_type: str
    segment: str
    variant: str
    flow_assets: list[str]
    pipeline: str | None = None
    copies: list[str] = []
    knowledge: list[str] = []
    methodologies: list[str] = []

class PromoteTemplateBody(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    category: str
    segment: str
    modality: str
    level: str
    estimated_time: str
    tags: list[str] = []
    status: str = "draft"
    version: str = Field(min_length=1, max_length=32)
    slug: str | None = None

def official_service(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(get_current_user)):
    return OfficialMarketplaceTemplateService(db, tenant, user)

def version_output(version: MarketplaceTemplateVersion):
    return {"id": str(version.id), "template_id": str(version.template_id), "slug": version.template.slug, "name": version.template.name, "version": version.version, "status": version.status, "source_flow_id": str(version.source_flow_id), "source_flow_version_id": str(version.source_flow_version_id), "manifest": version.manifest, "dependencies": version.dependencies, "checksum": version.checksum, "validation": version.validation_report, "created_at": version.created_at, "published_at": version.published_at}
def service(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(get_current_user)):
    return MarketplaceInstallationService(db, tenant, user)
def output(item):
    return {"id": str(item.id), "template_slug": item.template_slug, "template_type": item.template_type, "template_version": item.template_version, "variant": item.variant, "status": item.status, "installed_by_user_id": str(item.installed_by_user_id), "started_at": item.started_at, "completed_at": item.completed_at, "error": {"code": item.error_code, "summary": item.error_summary} if item.error_code else None, "created_resources": item.created_resources, "flow_ids": item.created_resources.get("flows", []), "blueprint_id": item.created_resources.get("blueprint_id"), "post_install_route": item.created_resources.get("post_install_route"), "dependencies": item.dependency_snapshot, "checklist": item.customization_state.get("checklist", []), "resources": [{"type": r.resource_type, "id": r.resource_id, "name": r.resource_name, "creation_status": r.creation_status, "rollback_status": r.rollback_status, "metadata": r.metadata_json} for r in item.resources]}
def translate(exc):
    if isinstance(exc, PermissionError): raise HTTPException(403, str(exc))
    if isinstance(exc, LookupError): raise HTTPException(404, str(exc))
    if isinstance(exc, ValueError): raise HTTPException(422, str(exc))
    raise exc
@router.get("/items/{slug}/installation-preview")
def preview(slug: str, variant: str = Query("Sem IA"), svc=Depends(service)):
    try: return svc.preview(slug, variant)
    except Exception as exc: translate(exc)
@router.get("/catalog")
def catalog(db: Session = Depends(get_db), user: TenantUser = Depends(get_current_user)):
    legacy = [{**item, "name": ASSETS[item["flow_assets"][0]]["name"] if item["flow_assets"] else item["key"]} for item in ITEMS.values()]
    official = db.scalars(select(MarketplaceTemplateVersion).join(MarketplaceTemplate).where(MarketplaceTemplateVersion.status == "published").order_by(MarketplaceTemplateVersion.published_at.desc())).all()
    return legacy + [{"key": v.template.key, "slug": v.template.slug, "name": v.template.name, "description": v.template.description, "category": v.template.category, "segment": v.template.segment, "modality": v.template.modality, "version": v.version, "official": True} for v in official]

@router.post("/official-templates/from-flow/{flow_id}")
def promote_flow(flow_id: UUID, body: PromoteTemplateBody, svc=Depends(official_service)):
    try: return version_output(svc.promote(flow_id, body))
    except Exception as exc: translate(exc)

@router.get("/official-templates")
def official_templates(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(get_current_user)):
    if user.role not in {"owner", "admin"} or str(user.tenant_id) != str(tenant.id): raise HTTPException(403, "official_template_forbidden")
    return [version_output(v) for v in db.scalars(select(MarketplaceTemplateVersion).join(MarketplaceTemplate).order_by(MarketplaceTemplateVersion.created_at.desc())).all()]

@router.post("/official-templates/{slug}/install")
def install_official(slug: str, svc=Depends(official_service)):
    try: return svc.install(slug)
    except Exception as exc: translate(exc)

@router.post("/official-template-versions/{version_id}/publish")
def publish_official(version_id: UUID, svc=Depends(official_service)):
    try: return version_output(svc.set_publication(version_id, True))
    except Exception as exc: translate(exc)

@router.post("/official-template-versions/{version_id}/unpublish")
def unpublish_official(version_id: UUID, svc=Depends(official_service)):
    try: return version_output(svc.set_publication(version_id, False))
    except Exception as exc: translate(exc)
@router.post("/composer/drafts/validate")
def validate_composer_draft(body: ComposerDraft, user: TenantUser = Depends(get_current_user)):
    if user.role not in {"owner", "admin"}: raise HTTPException(403, "marketplace_composer_forbidden")
    errors = []
    assets = []
    for key in body.flow_assets:
        asset = ASSETS.get(key)
        if not asset: errors.append(f"asset_not_found:{key}"); continue
        try: MarketplaceGraphValidator().validate(asset)
        except ValueError as exc: errors.append(str(exc))
        assets.append(asset)
    manifest = body.dict()
    return {"status": "invalid" if errors else "draft", "errors": errors, "manifest": manifest, "graph_previews": [asset["graph"] for asset in assets], "published": False}
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
