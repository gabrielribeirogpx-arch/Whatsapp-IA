from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.database import get_db
from app.services.flow_runtime_service import FlowRuntimeService

router = APIRouter(tags=["flow-runtime"])


@router.post("/runtime/test/{flow_id}")
def test_flow(flow_id: str, payload: dict[str, Any], db: Session = Depends(get_db)):
    service = FlowRuntimeService(db)
    input_text = str(payload.get("message", ""))
    result = service.execute_flow(flow_id, input_text)
    return result


@router.post("/runtime/session/{flow_id}")
def run_with_session(flow_id: str, payload: dict[str, Any], db: Session = Depends(get_db)):
    service = FlowRuntimeService(db)
    return service.execute_with_session(
        flow_id=flow_id,
        conversation_id=str(payload["conversation_id"]),
        input_text=str(payload.get("message", "")),
    )
