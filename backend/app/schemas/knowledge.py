import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class KnowledgeCreate(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1)


class KnowledgeCrawlRequest(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    depth: int = Field(default=1, ge=1, le=2)


class KnowledgeOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    title: str
    content: str
    created_at: datetime

    class Config:
        from_attributes = True


class KnowledgeUploadOut(BaseModel):
    source: str
    chunks_created: int


class KnowledgeCrawlOut(BaseModel):
    source: str
    pages_collected: int
    chunks_created: int
