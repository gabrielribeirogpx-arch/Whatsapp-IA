from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class IntegrationConnectionStatusOut(BaseModel):
    provider: str
    auth_type: str | None = None
    status: str
    connected: bool
    scopes: list[str] = []
    metadata: dict[str, Any] = {}
    expires_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)
