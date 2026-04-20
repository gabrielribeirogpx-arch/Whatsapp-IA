import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class BotRuleCreate(BaseModel):
    trigger: str = Field(min_length=1, max_length=255)
    response: str = Field(min_length=1)
    match_type: Literal["contains", "exact"] = "contains"


class BotRuleOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    trigger: str
    response: str
    match_type: Literal["contains", "exact"]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
