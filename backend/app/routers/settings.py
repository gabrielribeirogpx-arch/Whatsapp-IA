from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Tenant
from app.services.tenant_service import get_current_tenant

router = APIRouter(tags=["settings"])


class SettingsOut(BaseModel):
    token: str | None = None
    whatsapp_token: str | None = None
    phone_number_id: str = ""
    webhook_url: str | None = None
    webhook_status: str = "inactive"
    system_name: str = "WhatsApp IA"
    language: str = "pt-BR"


class SettingsUpdateIn(BaseModel):
    token: str | None = Field(default=None, max_length=512)
    whatsapp_token: str | None = Field(default=None, max_length=512)
    phone_number_id: str | None = Field(default=None, min_length=2, max_length=64)
    webhook_url: str | None = Field(default=None, max_length=500)
    webhook_status: str | None = Field(default=None, max_length=32)
    system_name: str | None = Field(default=None, min_length=2, max_length=150)
    language: str | None = Field(default=None, min_length=2, max_length=16)


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
        token_value = payload.whatsapp_token if payload.whatsapp_token is not None else payload.token
        if token_value is not None:
            tenant.whatsapp_token = token_value.strip() or None

        if payload.phone_number_id is not None:
            tenant.phone_number_id = payload.phone_number_id.strip()

        if payload.webhook_url is not None:
            tenant.webhook_url = payload.webhook_url.strip() or None

        if payload.webhook_status is not None:
            tenant.webhook_status = payload.webhook_status.strip() or "inactive"

        if payload.system_name is not None:
            tenant.name = payload.system_name.strip()

        if payload.language is not None:
            tenant.language = payload.language.strip()

        db.add(tenant)
        db.commit()
        db.refresh(tenant)
    except Exception as error:
        print("[SETTINGS ERROR]", error)
        raise

    return _serialize_settings(tenant)
