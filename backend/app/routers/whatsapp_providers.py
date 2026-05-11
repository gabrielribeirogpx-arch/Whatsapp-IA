from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tenant import Tenant
from app.schemas.whatsapp_business import TenantWhatsAppProviderCreate, TenantWhatsAppProviderOut, TenantWhatsAppProviderUpdate
from app.services import whatsapp_provider_service
from app.services.tenant_service import get_current_tenant

router = APIRouter(prefix="/api/whatsapp/providers", tags=["whatsapp-providers"])


@router.get("", response_model=list[TenantWhatsAppProviderOut])
def get_providers(request: Request, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    print("[WHATSAPP PROVIDERS LIST]", f"tenant_id={tenant.id}")
    return whatsapp_provider_service.list_providers(db, tenant.id)


@router.post("", response_model=TenantWhatsAppProviderOut)
def create_provider(request: Request, payload: TenantWhatsAppProviderCreate, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    print("[WHATSAPP PROVIDER CREATE]", f"tenant_id={tenant.id}")
    try:
        return whatsapp_provider_service.create_provider(db, tenant.id, payload)
    except Exception as exc:
        print(
            "[WHATSAPP PROVIDER CREATE ERROR]",
            f"tenant_id={tenant.id}",
            f"provider_type={payload.provider_type}",
            f"exception_type={type(exc).__name__}",
            f"message={str(exc)[:180]}",
        )
        raise HTTPException(status_code=500, detail="Erro ao criar provider. Verifique a configuração e tente novamente.") from exc


@router.patch("/{provider_id}", response_model=TenantWhatsAppProviderOut)
def patch_provider(provider_id: str, payload: TenantWhatsAppProviderUpdate, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    try:
        return whatsapp_provider_service.update_provider(db, tenant.id, provider_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{provider_id}/activate", response_model=TenantWhatsAppProviderOut)
def activate_provider(provider_id: str, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    print("[WHATSAPP PROVIDER ACTIVATE]", f"tenant_id={tenant.id}", f"provider_id={provider_id}")
    try:
        return whatsapp_provider_service.set_active_provider(db, tenant.id, provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{provider_id}/test")
def test_provider(provider_id: str, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    print("[WHATSAPP PROVIDER TEST]", f"tenant_id={tenant.id}", f"provider_id={provider_id}")
    try:
        return whatsapp_provider_service.test_provider_connection(db, tenant.id, provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.delete("/{provider_id}", status_code=204)
def remove_provider(provider_id: str, db: Session = Depends(get_db), tenant: Tenant = Depends(get_current_tenant)):
    try:
        whatsapp_provider_service.delete_provider(db, tenant.id, provider_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
