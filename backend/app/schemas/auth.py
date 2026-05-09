from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    full_name: str = Field(min_length=2, max_length=150)
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)
    business_name: str = Field(min_length=2, max_length=150)
    whatsapp_number: str = Field(min_length=2, max_length=64)
    business_segment: str = Field(min_length=2, max_length=120)
    intended_use: str = Field(min_length=2, max_length=200)
    team_size: str | None = Field(default=None, max_length=64)
    monthly_message_volume: str | None = Field(default=None, max_length=64)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)


class TenantAuthResponse(BaseModel):
    tenant_id: UUID
    slug: str
    token: str
