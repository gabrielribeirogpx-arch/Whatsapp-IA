from datetime import datetime

from pydantic import BaseModel, Field


class ConversationOut(BaseModel):
    id: int
    phone: str
    name: str
    status: str
    last_message: str
    updated_at: datetime

    class Config:
        from_attributes = True


class MessageOut(BaseModel):
    id: int
    phone: str
    content: str
    from_me: bool
    timestamp: datetime

    class Config:
        from_attributes = True


class SendMessageRequest(BaseModel):
    phone: str = Field(min_length=6, max_length=32)
    message: str = Field(min_length=1, max_length=4096)
    name: str | None = Field(default=None, max_length=150)


class ToggleAssignmentResponse(BaseModel):
    phone: str
    status: str
