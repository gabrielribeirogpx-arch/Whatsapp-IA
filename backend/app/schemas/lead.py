import uuid
from datetime import datetime

from pydantic import BaseModel

from backend.app.models.lead import LeadStage


class LeadOut(BaseModel):
    id: uuid.UUID
    phone: str
    name: str | None = None
    stage: LeadStage
    score: int
    last_message: str | None = None
    last_contact_at: datetime

    class Config:
        from_attributes = True


class LeadStageUpdateRequest(BaseModel):
    stage: LeadStage


class LeadStatsOut(BaseModel):
    total: int
    por_stage: dict[LeadStage, int]
