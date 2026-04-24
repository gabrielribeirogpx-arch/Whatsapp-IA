from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Tenant
from app.services.tenant_service import get_current_tenant

router = APIRouter(tags=["settings"])


class SettingsOut(BaseModel):
    token: str | None
    phone_number_id: str
    webhook_url: str | None
    webhook_status: str
    system_name: str
    language: str


class SettingsUpdateIn(BaseModel):
    token: str | None = Field(default=None, max_length=512)
    phone_number_id: str = Field(min_length=2, max_length=64)
    webhook_url: str | None = Field(default=None, max_length=500)
    webhook_status: str = Field(default="inactive", max_length=32)
    system_name: str = Field(min_length=2, max_length=150)
    language: str = Field(default="pt-BR", min_length=2, max_length=16)


def _serialize_settings(tenant: Tenant) -> SettingsOut:
    return SettingsOut(
        token=tenant.whatsapp_token,
        phone_number_id=tenant.phone_number_id,
        webhook_url=tenant.webhook_url,
        webhook_status=tenant.webhook_status or "inactive",
        system_name=tenant.name,
        language=tenant.language or "pt-BR",
    )


@router.get("/settings", response_model=SettingsOut)
def get_settings(tenant: Tenant = Depends(get_current_tenant)):
    return _serialize_settings(tenant)


@router.put("/settings", response_model=SettingsOut)
def update_settings(
    payload: SettingsUpdateIn,
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    tenant.whatsapp_token = payload.token.strip() if payload.token else None
    tenant.phone_number_id = payload.phone_number_id.strip()
    tenant.webhook_url = payload.webhook_url.strip() if payload.webhook_url else None
    tenant.webhook_status = payload.webhook_status.strip() or "inactive"
    tenant.name = payload.system_name.strip()
    tenant.language = payload.language.strip()

    db.add(tenant)
    db.commit()
    db.refresh(tenant)

    return _serialize_settings(tenant)
