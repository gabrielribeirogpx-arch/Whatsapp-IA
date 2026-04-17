import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ConversationOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    contact_id: uuid.UUID | None = None
    phone: str
    name: str
    avatar_url: str | None = None
    stage: str = "novo"
    score: int = 0
    status: str
    last_message: str
    updated_at: datetime

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    id: uuid.UUID
    content: str
    role: str
    created_at: datetime

    class Config:
        from_attributes = True


class SendMessageRequest(BaseModel):
    phone: str = Field(min_length=6, max_length=32)
    message: str = Field(min_length=1, max_length=4096)
    contact_id: uuid.UUID | None = None
    name: str | None = Field(default=None, max_length=150)


class ContactOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    phone: str
    name: str | None = None
    avatar_url: str | None = None
    stage: str
    score: int
    last_message_at: datetime | None = None
    last_message: str | None = None
    created_at: datetime

    class Config:
        from_attributes = True


class ToggleAssignmentResponse(BaseModel):
    phone: str
    status: str


class TenantLoginRequest(BaseModel):
    slug: str = Field(min_length=2, max_length=80)


class TenantUsageOut(BaseModel):
    plan: str
    is_blocked: bool
    max_monthly_messages: int
    messages_used_month: int
    usage_month: str


class TenantLoginResponse(BaseModel):
    tenant_id: uuid.UUID
    name: str
    slug: str
    usage: TenantUsageOut
