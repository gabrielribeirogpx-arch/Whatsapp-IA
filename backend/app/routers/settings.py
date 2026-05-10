from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Tenant
from app.schemas.settings import SettingsOut, SettingsUpdateIn
from app.services.tenant_service import get_current_tenant

router = APIRouter(tags=["settings"])


def _serialize_settings(tenant: Tenant) -> SettingsOut:
    return SettingsOut(
        token=tenant.whatsapp_token,
        whatsapp_token=tenant.whatsapp_token,
        phone_number_id=tenant.phone_number_id,
        webhook_url=tenant.webhook_url,
        webhook_status=tenant.webhook_status or "inactive",
        system_name=tenant.name or "WhatsApp IA",
        language=tenant.language or "pt-BR",
    )


@router.get("/settings", response_model=SettingsOut)
def get_settings(request: Request, tenant: Tenant = Depends(get_current_tenant)):
    tenant_id = getattr(request.state, "tenant_id", None)
    print("[SETTINGS GET]", tenant_id)
    return _serialize_settings(tenant)


@router.put("/settings", response_model=SettingsOut)
def update_settings(
    request: Request,
    payload: SettingsUpdateIn,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    tenant_id = getattr(request.state, "tenant_id", None)
    print("[SETTINGS SAVE]", tenant_id, payload.dict())
    try:
        disconnect_whatsapp = False
        token_value = payload.whatsapp_token if payload.whatsapp_token is not None else payload.token
        if token_value is not None:
            normalized_token = token_value.strip() or None
            tenant.whatsapp_token = normalized_token
            if normalized_token is None:
                disconnect_whatsapp = True

        if payload.phone_number_id is not None:
            normalized_phone_number_id = payload.phone_number_id.strip() or None
            tenant.phone_number_id = normalized_phone_number_id
            if normalized_phone_number_id is None:
                disconnect_whatsapp = True

        if payload.webhook_url is not None:
            tenant.webhook_url = payload.webhook_url.strip() or None

        if payload.webhook_status is not None:
            tenant.webhook_status = payload.webhook_status.strip() or "inactive"

        if disconnect_whatsapp:
            tenant.webhook_status = "inactive"
            print("[SETTINGS WHATSAPP DISCONNECTED]", f"tenant_id={tenant_id}")

        if payload.system_name is not None:
            tenant.name = payload.system_name.strip()

        if payload.language is not None:
            tenant.language = payload.language.strip()

        db.add(tenant)
        db.commit()
        db.refresh(tenant)
    except IntegrityError as error:
        db.rollback()
        print("[SETTINGS ERROR]", error)
        constraint_name = ""
        if getattr(error, "orig", None) is not None:
            constraint_name = getattr(getattr(error.orig, "diag", None), "constraint_name", "") or ""

        message = str(error)
        if "ix_tenants_phone_number_id" in constraint_name or "ix_tenants_phone_number_id" in message:
            raise HTTPException(
                status_code=409,
                detail="Este Phone Number ID já está vinculado a outro tenant. Use outro número ou desvincule do tenant anterior.",
            ) from error
        raise
    except Exception as error:
        db.rollback()
        print("[SETTINGS ERROR]", error)
        raise

    return _serialize_settings(tenant)
