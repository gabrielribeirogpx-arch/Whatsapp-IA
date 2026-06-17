from __future__ import annotations

from datetime import datetime
from typing import Any
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.flow_ai_execution import FlowAIExecution
from app.models.tenant import Tenant
from app.services.ai_execution_service import metrics
from app.services.tenant_service import get_current_tenant

router = APIRouter(prefix="/ai/executions", tags=["ai-executions"])


class AIExecutionOut(BaseModel):
    id: uuid.UUID
    tenant_id: uuid.UUID
    conversation_id: uuid.UUID | None
    session_id: uuid.UUID | None
    flow_id: uuid.UUID | None
    flow_version_id: uuid.UUID | None
    node_id: str
    node_type: str
    provider: str | None
    model: str | None
    started_at: datetime
    finished_at: datetime | None
    latency_ms: int | None
    status: str
    input_size: int | None
    output_size: int | None
    prompt_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    retrieval_mode: str | None
    confidence: float | None
    fallback_used: bool
    created_at: datetime
    metadata: dict[str, Any]


def _out(row: FlowAIExecution) -> AIExecutionOut:
    return AIExecutionOut(
        id=row.id, tenant_id=row.tenant_id, conversation_id=row.conversation_id, session_id=row.session_id, flow_id=row.flow_id,
        flow_version_id=row.flow_version_id, node_id=row.node_id, node_type=row.node_type, provider=row.provider, model=row.model,
        started_at=row.started_at, finished_at=row.finished_at, latency_ms=row.latency_ms, status=row.status, input_size=row.input_size,
        output_size=row.output_size, prompt_tokens=row.prompt_tokens, completion_tokens=row.completion_tokens, total_tokens=row.total_tokens,
        retrieval_mode=row.retrieval_mode, confidence=row.confidence, fallback_used=row.fallback_used, created_at=row.created_at,
        metadata=row.metadata_json or {},
    )


@router.get("")
def list_ai_executions(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    flow_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    node_type: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    status: str | None = None,
    fallback: bool | None = None,
    confidence_min: float | None = Query(None, ge=0, le=1),
    confidence_max: float | None = Query(None, ge=0, le=1),
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    stmt = select(FlowAIExecution).where(FlowAIExecution.tenant_id == tenant.id)
    for col, val in ((FlowAIExecution.flow_id, flow_id), (FlowAIExecution.conversation_id, conversation_id), (FlowAIExecution.session_id, session_id), (FlowAIExecution.node_type, node_type), (FlowAIExecution.provider, provider), (FlowAIExecution.model, model), (FlowAIExecution.status, status)):
        if val not in (None, ""):
            stmt = stmt.where(col == val)
    if fallback is not None:
        stmt = stmt.where(FlowAIExecution.fallback_used.is_(fallback))
    if confidence_min is not None:
        stmt = stmt.where(FlowAIExecution.confidence >= confidence_min)
    if confidence_max is not None:
        stmt = stmt.where(FlowAIExecution.confidence <= confidence_max)
    if date_from is not None:
        stmt = stmt.where(FlowAIExecution.created_at >= date_from)
    if date_to is not None:
        stmt = stmt.where(FlowAIExecution.created_at <= date_to)
    total = len(db.execute(stmt.with_only_columns(FlowAIExecution.id)).all())
    rows = db.execute(stmt.order_by(FlowAIExecution.created_at.desc(), FlowAIExecution.id.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"items": [_out(r).model_dump(mode="json") for r in rows], "page": page, "page_size": page_size, "total": total, "metrics": metrics(db, tenant.id)}


@router.get("/{execution_id}", response_model=AIExecutionOut)
def get_ai_execution(execution_id: uuid.UUID, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    row = db.execute(select(FlowAIExecution).where(FlowAIExecution.id == execution_id, FlowAIExecution.tenant_id == tenant.id)).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="AI execution not found")
    return _out(row)
