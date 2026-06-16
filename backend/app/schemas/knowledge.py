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
    source_id: uuid.UUID | None = None
    status: str = "ready"
    chunks_created: int


class KnowledgeSourceOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    type: str
    status: str
    original_filename: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    storage_url: str | None = None
    metadata_json: dict | None = None
    chunks_count: int = 0
    embedded_chunks_count: int = 0
    embedding_status: str = "text_only"
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class KnowledgeCrawlOut(BaseModel):
    source: str
    pages_collected: int
    chunks_created: int


class KnowledgeReindexOut(BaseModel):
    source_id: uuid.UUID
    chunks_total: int
    embedded: int
    failed: int
    status: str
