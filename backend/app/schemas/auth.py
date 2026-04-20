from uuid import UUID

from pydantic import BaseModel


class TenantAuthResponse(BaseModel):
    tenant_id: UUID
    slug: str
