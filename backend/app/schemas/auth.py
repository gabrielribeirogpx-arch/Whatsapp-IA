from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    # Register validation is deliberately performed by the endpoint so every
    # failure uses the public registration error contract.
    full_name: str = Field(max_length=150)
    email: str = Field(max_length=255)
    password: str = Field(max_length=128)
    confirm_password: str = Field(max_length=128)
    business_name: str = Field(max_length=150)
    whatsapp_number: str = Field(max_length=64)
    business_segment: str = Field(max_length=120)
    intended_use: str = Field(max_length=200)
    team_size: str | None = Field(default=None, max_length=64)
    monthly_message_volume: str | None = Field(default=None, max_length=64)
    turnstile_token: str | None = Field(default=None, max_length=4096)


class LoginRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=8, max_length=128)
    turnstile_token: str | None = Field(default=None, max_length=4096)


class TenantAuthResponse(BaseModel):
    tenant_id: UUID
    slug: str
    token: str


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    turnstile_token: str | None = Field(default=None, max_length=4096)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=20, max_length=512)
    new_password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)
