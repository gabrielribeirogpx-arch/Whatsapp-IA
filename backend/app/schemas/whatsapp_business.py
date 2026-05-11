from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.whatsapp_enums import ProviderTypeEnum, TemplateCategoryEnum, TemplateStatusEnum


class TenantWhatsAppProviderCreate(BaseModel):
    provider_type: ProviderTypeEnum
    display_name: str | None = None
    waba_id: str | None = None
    phone_number_id: str | None = None
    business_id: str | None = None
    bsp_account_id: str | None = None
    access_token: str | None = None
    app_id: str | None = None
    app_secret: str | None = None
    api_key: str | None = None
    webhook_verify_token: str | None = None
    webhook_url: str | None = None


class TenantWhatsAppProviderUpdate(TenantWhatsAppProviderCreate):
    provider_type: ProviderTypeEnum | None = None
    status: str | None = None


class TenantWhatsAppProviderOut(BaseModel):
    id: UUID
    tenant_id: UUID
    provider_type: ProviderTypeEnum
    display_name: str | None = None
    waba_id: str | None = None
    phone_number_id: str | None = None
    business_id: str | None = None
    bsp_account_id: str | None = None
    app_id: str | None = None
    webhook_verify_token: str | None = None
    webhook_url: str | None = None
    is_active: bool
    status: Literal["disconnected", "connected", "active", "invalid_config"]
    metadata_json: dict = Field(default_factory=dict)
    last_connection_check_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}

    @field_validator("metadata_json", mode="before")
    @classmethod
    def ensure_metadata_json(cls, value):
        return value or {}


class WhatsAppTemplateCreate(BaseModel):
    provider_id: UUID | None = None
    name: str
    category: TemplateCategoryEnum | None = TemplateCategoryEnum.UTILITY
    language: str = "pt_BR"
    body_text: str | None = None
    body_raw_meta: str | None = None
    body_preview: str | None = None
    header_json: dict = Field(default_factory=dict)
    footer_text: str | None = None
    buttons_json: list = Field(default_factory=list)
    variables_json: list = Field(default_factory=list)


class WhatsAppTemplateUpdate(BaseModel):
    provider_id: UUID | None = None
    name: str | None = None
    category: TemplateCategoryEnum | None = None
    language: str | None = None
    body_text: str | None = None
    body_raw_meta: str | None = None
    body_preview: str | None = None
    header_json: dict | None = None
    footer_text: str | None = None
    buttons_json: list | None = None
    variables_json: list | None = None
    status: TemplateStatusEnum | None = None


class WhatsAppTemplateOut(BaseModel):
    id: UUID
    tenant_id: UUID
    provider_id: UUID | None = None
    name: str
    category: TemplateCategoryEnum | None = None
    language: str
    status: TemplateStatusEnum
    body_text: str
    body_raw_meta: str
    body_preview: str | None = None
    header_json: dict = Field(default_factory=dict)
    footer_text: str | None = None
    buttons_json: list = Field(default_factory=list)
    variables_json: list = Field(default_factory=list)
    metadata_json: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime
    model_config = {"from_attributes": True}
