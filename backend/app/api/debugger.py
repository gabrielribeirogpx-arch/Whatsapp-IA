from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.debugger.execution_replay_service import build_execution_replay, get_execution_path
from app.debugger.execution_serializer import ReplayExecution, ReplayEvent

router = APIRouter(prefix="/api/debugger", tags=["debugger"])


@router.get("/executions/{trace_id}", response_model=ReplayExecution)
def get_replay_execution(trace_id: str, db: Session = Depends(get_db)) -> ReplayExecution:
    replay = build_execution_replay(db, trace_id)
    if not replay.timeline:
        raise HTTPException(status_code=404, detail="Execution trace not found")
    return replay


@router.get("/executions/{trace_id}/timeline", response_model=list[ReplayEvent])
def get_replay_timeline(trace_id: str, db: Session = Depends(get_db)) -> list[ReplayEvent]:
    replay = build_execution_replay(db, trace_id)
    if not replay.timeline:
        raise HTTPException(status_code=404, detail="Execution trace not found")
    return replay.timeline


@router.get("/executions/{trace_id}/path", response_model=list[str])
def get_replay_path(trace_id: str, db: Session = Depends(get_db)) -> list[str]:
    path = get_execution_path(db, trace_id)
    if not path:
        raise HTTPException(status_code=404, detail="Execution trace not found")
    return path
