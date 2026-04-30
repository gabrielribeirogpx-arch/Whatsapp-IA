from uuid import UUID

from pydantic import BaseModel


class TenantAuthResponse(BaseModel):
    tenant_id: UUID
    slug: str
    token: str


class TenantProfileResponse(BaseModel):
    tenant_id: UUID
    slug: str
    name: str
    phone_number_id: str
    plan: str
    language: str
