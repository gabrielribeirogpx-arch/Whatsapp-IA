from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AccountProfileOut(BaseModel):
    id: UUID
    name: str
    email: str
    avatar_url: str | None = None
    company: str | None = None
    job_title: str | None = None
    role: str


class AccountProfileUpdateIn(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    email: str = Field(min_length=5, max_length=255)
    avatar_url: str | None = Field(default=None, max_length=500)
    company: str | None = Field(default=None, max_length=150)
    job_title: str | None = Field(default=None, max_length=120)


class AccountPreferencesOut(BaseModel):
    language: str
    timezone: str
    email_notifications: bool
    whatsapp_notifications: bool


class AccountPreferencesUpdateIn(BaseModel):
    language: str = Field(min_length=2, max_length=16)
    timezone: str = Field(min_length=2, max_length=80)
    email_notifications: bool = True
    whatsapp_notifications: bool = True


class AccountSecurityOut(BaseModel):
    last_login_at: datetime | None = None
    last_login_ip: str | None = None
    active_sessions_count: int = 0
    blocked_login_attempts: int = 0
    turnstile_status: str = "Ativo"
    protection_status: str = "Protegido"
    active_sessions: list[dict]
    history: list[dict[str, str | None]]
    mfa_status: str


class AccountPasswordUpdateIn(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
    confirm_password: str = Field(min_length=8, max_length=128)


class AccountMeOut(BaseModel):
    profile: AccountProfileOut
    preferences: AccountPreferencesOut
    security: AccountSecurityOut


class WorkspaceUserOut(BaseModel):
    id: UUID
    name: str
    email: str
    role: str
    status: str
    last_access_at: datetime | None = None


class WorkspaceUserInviteIn(BaseModel):
    name: str = Field(min_length=2, max_length=150)
    email: str = Field(min_length=5, max_length=255)
    role: str = Field(default="member", max_length=32)


class WorkspaceUserUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=150)
    role: str | None = Field(default=None, max_length=32)
    status: str | None = Field(default=None, max_length=32)


class AuditLogOut(BaseModel):
    id: UUID
    tenant_id: UUID | None = None
    user_id: UUID | None = None
    user_name: str | None = None
    user_email: str | None = None
    action: str
    entity_type: str | None = None
    entity_id: str | None = None
    metadata_json: dict = Field(default_factory=dict)
    ip_address: str | None = None
    user_agent: str | None = None
    created_at: datetime | None = None
