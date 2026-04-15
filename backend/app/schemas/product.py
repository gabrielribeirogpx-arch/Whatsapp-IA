import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class ProductBase(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    description: str | None = None
    price: str | None = Field(default=None, max_length=120)
    benefits: str | None = None
    objections: str | None = None
    target_customer: str | None = None


class ProductCreate(ProductBase):
    pass


class ProductUpdate(ProductBase):
    pass


class ProductOut(ProductBase):
    id: uuid.UUID
    tenant_id: uuid.UUID
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
