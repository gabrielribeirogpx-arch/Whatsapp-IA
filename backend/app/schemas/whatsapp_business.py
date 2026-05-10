from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TenantWhatsAppProviderCreate(BaseModel):
    provider_type: str
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


class TenantWhatsAppProviderUpdate(BaseModel):
    provider_type: str | None = None
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
    status: str | None = None


class TenantWhatsAppProviderOut(BaseModel):
    id: UUID
    tenant_id: UUID
    provider_type: str
    display_name: str | None = None
    waba_id: str | None = None
    phone_number_id: str | None = None
    business_id: str | None = None
    bsp_account_id: str | None = None
    app_id: str | None = None
    webhook_verify_token: str | None = None
    webhook_url: str | None = None
    is_active: bool
    status: str
    metadata_json: dict = Field(default_factory=dict)
    last_connection_check_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class WhatsAppTemplateCreate(BaseModel):
    provider_id: UUID | None = None
    name: str
    category: str | None = None
    language: str = "pt_BR"
    body_text: str
    header_json: dict = Field(default_factory=dict)
    footer_text: str | None = None
    buttons_json: list = Field(default_factory=list)
    variables_json: list = Field(default_factory=list)


class WhatsAppTemplateUpdate(BaseModel):
    provider_id: UUID | None = None
    name: str | None = None
    category: str | None = None
    language: str | None = None
    body_text: str | None = None
    header_json: dict | None = None
    footer_text: str | None = None
    buttons_json: list | None = None
    variables_json: list | None = None
    status: str | None = None


class WhatsAppTemplateOut(BaseModel):
    id: UUID
    tenant_id: UUID
    provider_id: UUID | None = None
    name: str
    category: str | None = None
    language: str
    status: str
    body_text: str
    header_json: dict = Field(default_factory=dict)
    footer_text: str | None = None
    buttons_json: list = Field(default_factory=list)
    variables_json: list = Field(default_factory=list)
    metadata_json: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
