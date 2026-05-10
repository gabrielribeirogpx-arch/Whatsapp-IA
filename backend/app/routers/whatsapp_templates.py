from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tenant import Tenant
from app.schemas.whatsapp_business import WhatsAppTemplateCreate, WhatsAppTemplateOut, WhatsAppTemplateUpdate
from app.services import whatsapp_template_service
from app.services.tenant_service import get_current_tenant

router = APIRouter(prefix="/api/whatsapp/templates", tags=["whatsapp-templates"])

@router.get("", response_model=list[WhatsAppTemplateOut])
def get_templates(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    return whatsapp_template_service.list_templates(db, tenant.id)

@router.post("", response_model=WhatsAppTemplateOut)
def create_template(payload: WhatsAppTemplateCreate, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    print("[WHATSAPP TEMPLATE CREATE]", f"tenant_id={tenant.id}", f"provider_id={payload.provider_id}")
    return whatsapp_template_service.create_template(db, tenant.id, payload)

@router.patch("/{template_id}", response_model=WhatsAppTemplateOut)
def patch_template(template_id: str, payload: WhatsAppTemplateUpdate, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    try:
        return whatsapp_template_service.update_template(db, tenant.id, template_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.delete("/{template_id}", status_code=204)
def remove_template(template_id: str, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    try:
        whatsapp_template_service.delete_template(db, tenant.id, template_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/{template_id}/submit", response_model=WhatsAppTemplateOut)
def submit_template(template_id: str, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    print("[WHATSAPP TEMPLATE SUBMIT]", f"tenant_id={tenant.id}", f"template_id={template_id}")
    try:
        return whatsapp_template_service.submit_template_placeholder(db, tenant.id, template_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

@router.post("/sync")
def sync_templates(db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    print("[WHATSAPP TEMPLATE SYNC]", f"tenant_id={tenant.id}")
    return whatsapp_template_service.sync_templates_placeholder(db, tenant.id)
