from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.flow_runtime_service import FlowRuntimeService
from app.services.flow_runtime_queue import enqueue_run_flow_job

router = APIRouter(tags=["flow-runtime"])


@router.post("/runtime/test/{flow_id}")
def test_flow(flow_id: str, payload: dict[str, Any], request: Request, db: Session = Depends(get_db)):
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        raise HTTPException(status_code=401, detail="Authorization token is required")
    service = FlowRuntimeService(db, tenant_id=tenant_id)
    input_text = str(payload.get("message", ""))
    result = service.execute_flow(flow_id, input_text)
    return result


@router.post("/runtime/session/{flow_id}")
def run_with_session(flow_id: str, payload: dict[str, Any], request: Request, db: Session = Depends(get_db)):
    tenant_id = getattr(request.state, "tenant_id", None)
    if tenant_id is None:
        raise HTTPException(status_code=401, detail="Authorization token is required")

    conversation_id = str(payload["conversation_id"])
    message = str(payload.get("message", ""))
    job_id = enqueue_run_flow_job(flow_id=flow_id, conversation_id=conversation_id, message=message)
    return {
        "queued": True,
        "job_id": job_id,
        "flow_id": flow_id,
        "conversation_id": conversation_id,
    }
