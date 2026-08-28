from typing import Any
from pydantic import BaseModel, Field
class AppointmentPolicyUpdate(BaseModel):
    timezone: str = "America/Sao_Paulo"
    default_duration_minutes: int = Field(60, gt=0)
    slot_interval_minutes: int = Field(60, gt=0)
    input_mode: str = "exact_or_period"
    business_hours: dict[str, list[dict[str, str]]] = Field(default_factory=dict)
class AppointmentPolicyOut(AppointmentPolicyUpdate): pass
