from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tenant import Tenant
from app.services.tenant_service import get_current_tenant
from app.services.long_term_memory_service import delete_fact, list_memories, store_fact, update_fact

router = APIRouter(prefix='/ai/memories', tags=['ai-memories'])

class MemoryIn(BaseModel):
    contact_id: uuid.UUID | None = None
    fact_text: str = Field(min_length=1, max_length=1000)
    fact_type: str = 'custom'
    importance_score: float = Field(0.5, ge=0, le=1)
    metadata: dict[str, Any] | None = None

class MemoryUpdate(BaseModel):
    fact_text: str | None = Field(None, max_length=1000)
    fact_type: str | None = None
    importance_score: float | None = Field(None, ge=0, le=1)
    expires_at: datetime | None = None
    metadata: dict[str, Any] | None = None

@router.get('')
def get_memories(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db), contact_id: uuid.UUID | None = None, query: str | None = None, fact_type: str | None = None, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    return {'items': list_memories(db, tenant.id, contact_id=contact_id, query=query, fact_type=fact_type, limit=limit, offset=offset)}

@router.post('')
def create_memory(payload: MemoryIn, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    row=store_fact(db, tenant.id, payload.contact_id, payload.fact_text, payload.fact_type, payload.importance_score, source='manual', metadata=payload.metadata)
    if not row: raise HTTPException(status_code=400, detail='memory_not_saved')
    db.commit(); return {'id': str(row.id)}

@router.put('/{memory_id}')
def put_memory(memory_id: uuid.UUID, payload: MemoryUpdate, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    row=update_fact(db, tenant.id, memory_id, **payload.model_dump(exclude_unset=True))
    if not row: raise HTTPException(status_code=404, detail='memory_not_found')
    db.commit(); return {'id': str(row.id)}

@router.delete('/{memory_id}')
def remove_memory(memory_id: uuid.UUID, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    if not delete_fact(db, tenant.id, memory_id): raise HTTPException(status_code=404, detail='memory_not_found')
    db.commit(); return {'ok': True}
