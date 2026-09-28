import re
from uuid import UUID
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models import MarketplaceInstallation, MarketplaceTemplate, MarketplaceTemplateVersion, Tenant, TenantUser
from app.services.official_marketplace_template_service import OfficialMarketplaceTemplateService
from app.routers.account import get_current_user
from app.services.marketplace_installation_service import MarketplaceInstallationService
from app.marketplace_assets import ASSETS, ITEMS, MarketplaceGraphValidator
from app.services.tenant_service import get_current_tenant
from app.schemas.assistant_configuration import (AssistantActivationRequest, AssistantActivationResponse,
    AssistantConfigurationResponse, AssistantConfigurationUpdate, AssistantConfiguratorResponse, AssistantMaterializationRequest,
    AssistantMaterializationResponse)
from app.security.workspace_rbac import WorkspacePermission, require_permission, require_same_tenant
from app.services.administrative_audit import require_administrative_permission
from app.services.assistant_configuration_service import (
    get_installation_for_configuration,
    serialize_configuration,
    update_configuration,
)
from app.services.assistant_flow_management_service import detect_flow_drift
from app.services.assistant_materialization_service import materialize_configuration
from app.services.assistant_activation_service import activate_assistant_configuration
from app.services.assistant_configurator_service import AssistantConfiguratorService

router = APIRouter(prefix="/marketplace", tags=["marketplace"])
class InstallBody(BaseModel):
    variant: str = "Sem IA"

class OfficialInstallBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version_id: UUID
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

class AssistantTemplateMapping(BaseModel):
    """The only graph references a browser may submit during promotion."""

    model_config = ConfigDict(extra="forbid")

    clinic_name_node_id: UUID
    clinic_name_field: str
    services_node_id: UUID
    calendar_node_ids: list[UUID] = Field(min_length=1)
    handoff_node_ids: list[UUID] = Field(min_length=1)


class PromoteTemplateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

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
    template_kind: str = "flow"
    assistant_mapping: AssistantTemplateMapping | None = None

def official_service(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(get_current_user)):
    return OfficialMarketplaceTemplateService(db, tenant, user)

def version_output(version: MarketplaceTemplateVersion):
    return {"id": str(version.id), "template_id": str(version.template_id), "slug": version.template.slug, "name": version.template.name, "version": version.version, "status": version.status, "source_flow_id": str(version.source_flow_id), "source_flow_version_id": str(version.source_flow_version_id), "manifest": version.manifest, "dependencies": version.dependencies, "checksum": version.checksum, "validation": version.validation_report, "certification_status": version.certification_status, "certification_version": version.certification_version, "candidate_checksum": version.candidate_checksum, "certified_at": version.certified_at, "created_at": version.created_at, "published_at": version.published_at}
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
    def version_key(value: MarketplaceTemplateVersion):
        # Versions are authored as strings. Natural token ordering preserves the
        # existing version semantics (1.10 > 1.2), with publication/creation/id
        # as deterministic tie-breakers for otherwise equivalent labels.
        natural = tuple((0, int(part)) if part.isdigit() else (1, part.lower())
                        for part in re.findall(r"\d+|[^\d]+", value.version))
        return natural, value.published_at or value.created_at, value.created_at, str(value.id)

    legacy = []
    for item in ITEMS.values():
        asset = ASSETS[item["flow_assets"][0]] if item["flow_assets"] else None
        legacy.append({
            "source": "legacy", "key": item["key"], "slug": item["key"],
            "name": asset["name"] if asset else item["key"],
            "description": asset.get("description") if asset else None,
            "category": item["template_type"],
            "segment": asset.get("metadata", {}).get("segment", "Geral") if asset else "Geral",
            "modality": (item.get("variants") or ["no_ai"])[0], "version": item["version"],
            "status": "published", "template_type": item["template_type"],
            "capabilities": [], "commercial": {"availability": item["availability"]},
        })
    published = db.scalars(select(MarketplaceTemplateVersion).join(MarketplaceTemplate).where(
        MarketplaceTemplateVersion.status == "published",
        MarketplaceTemplateVersion.certification_status.in_(("certified", "legacy_unverified")),
    )).all()
    latest = {}
    for version in published:
        current = latest.get(version.template_id)
        if current is None or version_key(version) > version_key(current):
            latest[version.template_id] = version
    official = [{
        "source": "official", "key": v.template.key, "template_id": str(v.template_id),
        "version_id": str(v.id), "slug": v.template.slug, "name": v.template.name,
        "description": v.template.description, "category": v.template.category,
        "segment": v.template.segment, "modality": v.template.modality,
        "version": v.version, "status": v.status, "template_type": "official_flow",
        "certification": getattr(v, "certification_status", "legacy_unverified"),
        "capabilities": list(v.manifest.get("capabilities", [])) if isinstance(v.manifest, dict) else [],
        "commercial": {
            "estimated_time": v.manifest.get("estimated_time") if isinstance(v.manifest, dict) else None,
            "level": v.manifest.get("level") if isinstance(v.manifest, dict) else None,
            "tags": v.manifest.get("tags", []) if isinstance(v.manifest, dict) else [],
            "availability": "installable_real",
        },
    } for v in sorted(latest.values(), key=version_key, reverse=True)]
    return legacy + official

@router.post("/official-templates/from-flow/{flow_id}")
def promote_flow(flow_id: UUID, body: PromoteTemplateBody, svc=Depends(official_service)):
    try: return version_output(svc.promote(flow_id, body))
    except Exception as exc: translate(exc)

@router.get("/official-templates")
def official_templates(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(get_current_user)):
    if user.role not in {"owner", "admin"} or str(user.tenant_id) != str(tenant.id): raise HTTPException(403, "official_template_forbidden")
    return [version_output(v) for v in db.scalars(select(MarketplaceTemplateVersion).join(MarketplaceTemplate).order_by(MarketplaceTemplateVersion.created_at.desc())).all()]

@router.post("/official-templates/{slug}/install")
def install_official(slug: str, body: OfficialInstallBody | None = None, svc=Depends(official_service)):
    try: return svc.install(slug, body.version_id if body else None)
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

@router.get("/installations/{installation_id}/configuration", response_model=AssistantConfigurationResponse)
def get_assistant_configuration(
    installation_id: UUID,
    request: Request,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    user: TenantUser = Depends(get_current_user),
):
    require_same_tenant(user, tenant.id)
    require_administrative_permission(
        db, user, WorkspacePermission.VIEW_FLOWS, request=request,
        action="assistant_configuration_viewed",
        resource_type="marketplace_installation_assistant_configuration",
        resource_id=installation_id,
    )
    installation = get_installation_for_configuration(db, installation_id, tenant.id)
    management = detect_flow_drift(
        db, installation=installation, tenant_id=tenant.id,
        actor_id=user.id, request=request,
    )
    db.commit()
    return serialize_configuration(installation, management.public_dict())


@router.get("/installations/{installation_id}/configurator", response_model=AssistantConfiguratorResponse)
def get_assistant_configurator(
    installation_id: UUID,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    user: TenantUser = Depends(get_current_user),
):
    """Return the complete, read-only product projection for the simple UI."""
    require_same_tenant(user, tenant.id)
    # Unlike administrative mutations, a denied GET must not emit an audit write.
    require_permission(user, WorkspacePermission.VIEW_FLOWS)
    return AssistantConfiguratorService(db).read(
        installation_id=installation_id, tenant_id=tenant.id, user=user,
    )

@router.put("/installations/{installation_id}/configuration", response_model=AssistantConfigurationResponse)
def put_assistant_configuration(
    installation_id: UUID,
    payload: AssistantConfigurationUpdate,
    request: Request,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
    user: TenantUser = Depends(get_current_user),
):
    require_same_tenant(user, tenant.id)
    require_administrative_permission(
        db, user, WorkspacePermission.MANAGE_SETTINGS, request=request,
        action="assistant_configuration_updated",
        resource_type="marketplace_installation_assistant_configuration",
        resource_id=installation_id,
    )
    installation = update_configuration(
        db, installation_id=installation_id, tenant_id=tenant.id,
        actor=user, payload=payload, request=request,
    )
    management = detect_flow_drift(
        db, installation=installation, tenant_id=tenant.id,
        actor_id=user.id, request=request,
    )
    db.commit()
    return serialize_configuration(installation, management.public_dict())

@router.post("/installations/{installation_id}/materialize", response_model=AssistantMaterializationResponse)
def materialize_assistant_configuration(
    installation_id: UUID, payload: AssistantMaterializationRequest, request: Request,
    db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant),
    user: TenantUser = Depends(get_current_user),
):
    require_same_tenant(user, tenant.id)
    for permission in (WorkspacePermission.MANAGE_SETTINGS, WorkspacePermission.MANAGE_FLOWS):
        require_administrative_permission(
            db, user, permission, request=request, action="assistant_configuration_materialized",
            resource_type="marketplace_installation_flow_management", resource_id=installation_id,
        )
    return materialize_configuration(
        db, installation_id=installation_id, tenant_id=tenant.id, actor_id=user.id,
        payload=payload, request=request,
    )


@router.post("/installations/{installation_id}/activate", response_model=AssistantActivationResponse)
def activate_assistant(
    installation_id: UUID, payload: AssistantActivationRequest, request: Request,
    db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant),
    user: TenantUser = Depends(get_current_user),
):
    require_same_tenant(user, tenant.id)
    for permission in (
        WorkspacePermission.MANAGE_SETTINGS, WorkspacePermission.MANAGE_FLOWS,
        WorkspacePermission.PUBLISH_FLOWS, WorkspacePermission.ACTIVATE_FLOWS,
    ):
        require_administrative_permission(
            db, user, permission, request=request, action="assistant_activated",
            resource_type="marketplace_installation", resource_id=installation_id,
        )
    return activate_assistant_configuration(
        db, installation_id=installation_id, tenant_id=tenant.id, actor_id=user.id,
        payload=payload, request=request,
    )
@router.post("/installations/{installation_id}/retry")
def retry(installation_id: UUID, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), svc=Depends(service)):
    item = owned(installation_id, db, tenant); svc._event("template_install_retried", item); db.commit(); return output(item)
@router.post("/installations/{installation_id}/rollback")
def rollback(installation_id: UUID, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant), svc=Depends(service)):
    return output(svc.rollback(owned(installation_id, db, tenant)))
