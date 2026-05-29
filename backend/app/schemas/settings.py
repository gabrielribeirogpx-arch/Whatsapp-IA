from pydantic import BaseModel, Field


class SettingsOut(BaseModel):
    token: str | None = None
    whatsapp_token: str | None = None
    phone_number_id: str | None = None
    webhook_url: str | None = None
    webhook_status: str = "inactive"
    system_name: str = "WhatsApp IA"
    language: str = "pt-BR"
    workspace_profile: str = "private_sales"


class SettingsUpdateIn(BaseModel):
    token: str | None = Field(default=None, max_length=512)
    whatsapp_token: str | None = Field(default=None, max_length=512)
    phone_number_id: str | None = Field(default=None, max_length=64)
    webhook_url: str | None = Field(default=None, max_length=500)
    webhook_status: str | None = Field(default=None, max_length=32)
    system_name: str | None = Field(default=None, min_length=2, max_length=150)
    language: str | None = Field(default=None, min_length=2, max_length=16)
    workspace_profile: str | None = Field(default=None, pattern="^(private_sales|government)$")
