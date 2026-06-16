from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

AIProvider = Literal["openai", "gemini", "anthropic", "wazza_default"]


class TenantAISettingsOut(BaseModel):
    tenant_id: UUID
    provider: AIProvider = "wazza_default"
    chat_model: str | None = None
    temperature: float = 0.2
    max_tokens: int = 1200
    embedding_provider: str | None = None
    embedding_model: str | None = None
    is_enabled: bool = True
    has_api_key: bool = False


class TenantAISettingsUpdate(BaseModel):
    provider: AIProvider = "wazza_default"
    chat_model: str | None = Field(default=None, max_length=120)
    api_key: str | None = Field(default=None, max_length=4096)
    temperature: float = Field(default=0.2, ge=0, le=2)
    max_tokens: int = Field(default=1200, ge=1, le=8000)
    embedding_provider: str | None = Field(default=None, max_length=32)
    embedding_model: str | None = Field(default=None, max_length=120)
    is_enabled: bool = True


class TenantAISettingsTestRequest(BaseModel):
    provider: AIProvider | None = None
    chat_model: str | None = None
    api_key: str | None = Field(default=None, max_length=4096)


class TenantAISettingsTestOut(BaseModel):
    ok: bool
    message: str
