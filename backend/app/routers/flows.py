from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Tenant
from app.services.flow_engine_service import get_flow_graph, save_flow_graph
from app.services.tenant_service import get_current_tenant

router = APIRouter(prefix="/api/flows", tags=["flows"])


class FlowBuilderPayload(BaseModel):
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


@router.get("/{flow_id}")
def get_flow(
    flow_id: str,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    try:
        return get_flow_graph(db=db, tenant_id=tenant.id, flow_id=flow_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/{flow_id}")
def upsert_flow(
    flow_id: str,
    payload: FlowBuilderPayload,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    try:
        result = save_flow_graph(
            db=db,
            tenant_id=tenant.id,
            flow_id=flow_id,
            nodes=payload.nodes,
            edges=payload.edges,
        )
        db.commit()
        return result
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception:
        db.rollback()
        raise
