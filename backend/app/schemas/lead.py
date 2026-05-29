import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.lead import LeadSource, LeadStage, LeadStatus, LeadTemperature


class LeadOut(BaseModel):
    id: uuid.UUID
    phone: str
    name: str | None = None
    stage: LeadStage
    stage_id: uuid.UUID | None = None
    temperature: LeadTemperature = LeadTemperature.COLD
    score: int
    email: str | None = None
    source: LeadSource = LeadSource.WHATSAPP
    status: LeadStatus = LeadStatus.ACTIVE
    owner_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    last_message: str | None = None
    last_contact_at: datetime
    last_interaction: datetime | None = None
    entered_stage_at: datetime | None = None
    updated_at: datetime | None = None

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
    email: str | None = None
    source: LeadSource = LeadSource.WHATSAPP
    status: LeadStatus = LeadStatus.ACTIVE
    owner_id: uuid.UUID | None = None
    contact_id: uuid.UUID | None = None
    conversation_id: uuid.UUID | None = None
    stage_id: uuid.UUID | None = None
    last_interaction: datetime | None = None
    entered_stage_at: datetime | None = None
    updated_at: datetime | None = None

    class Config:
        from_attributes = True


class PipelineStageOut(BaseModel):
    id: uuid.UUID
    name: str
    position: int
    is_final_stage: bool = False
    leads: list[PipelineLeadOut]


class LeadStatsOut(BaseModel):
    total: int
    por_stage: dict[LeadStage, int]
