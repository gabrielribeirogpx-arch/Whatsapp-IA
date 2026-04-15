import uuid
from datetime import datetime

from pydantic import BaseModel

from backend.app.models.lead import LeadStage, LeadTemperature


class LeadOut(BaseModel):
    id: uuid.UUID
    phone: str
    name: str | None = None
    stage: LeadStage
    stage_id: uuid.UUID | None = None
    temperature: LeadTemperature = LeadTemperature.COLD
    score: int
    last_message: str | None = None
    last_contact_at: datetime
    last_interaction: datetime | None = None

    class Config:
        from_attributes = True


class LeadStageUpdateRequest(BaseModel):
    stage: LeadStage


class LeadMoveRequest(BaseModel):
    stage_id: uuid.UUID


class PipelineLeadOut(BaseModel):
    id: uuid.UUID
    name: str | None = None
    phone: str
    last_message: str | None = None
    temperature: LeadTemperature
    score: int
    stage_id: uuid.UUID | None = None
    last_interaction: datetime | None = None

    class Config:
        from_attributes = True


class PipelineStageOut(BaseModel):
    id: uuid.UUID
    name: str
    position: int
    leads: list[PipelineLeadOut]


class LeadStatsOut(BaseModel):
    total: int
    por_stage: dict[LeadStage, int]
