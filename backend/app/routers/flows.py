from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Tenant
from app.services.flow_engine_service import get_flow_graph, save_flow_graph

router = APIRouter(prefix="/api/flows", tags=["flows"])


class FlowBuilderPayload(BaseModel):
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


_EMPTY_FLOW = {"nodes": [], "edges": []}


def _normalize_flow_response(payload: dict[str, Any] | None) -> dict[str, list[dict[str, Any]]]:
    if not payload:
        return dict(_EMPTY_FLOW)

    return {
        "nodes": payload.get("nodes") or [],
        "edges": payload.get("edges") or [],
    }


def _resolve_tenant(db: Session, tenant_id: str) -> Tenant | None:
    try:
        parsed_tenant_id = uuid.UUID(tenant_id)
    except ValueError:
        return None

    return db.execute(select(Tenant).where(Tenant.id == parsed_tenant_id)).scalars().first()


@router.get("/{tenant_id}")
def get_tenant_flow(
    tenant_id: str,
    db: Session = Depends(get_db),
):
    tenant = _resolve_tenant(db=db, tenant_id=tenant_id)
    if not tenant:
        return dict(_EMPTY_FLOW)

    graph = get_flow_graph(db=db, tenant_id=tenant.id, flow_id="default")
    return _normalize_flow_response(graph)


@router.post("/{tenant_id}")
def save_tenant_flow(
    tenant_id: str,
    payload: FlowBuilderPayload,
    db: Session = Depends(get_db),
):
    tenant = _resolve_tenant(db=db, tenant_id=tenant_id)
    if not tenant:
        return dict(_EMPTY_FLOW)

    save_flow_graph(
        db=db,
        tenant_id=tenant.id,
        flow_id="default",
        nodes=payload.nodes or [],
        edges=payload.edges or [],
    )
    db.commit()

    graph = get_flow_graph(db=db, tenant_id=tenant.id, flow_id="default")
    return _normalize_flow_response(graph)
