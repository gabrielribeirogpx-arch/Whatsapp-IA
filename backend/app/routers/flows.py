from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Flow, FlowVersion, Tenant
from app.services.flow_analytics_service import get_flow_analytics
from app.services.flow_engine_service import get_flow_graph, save_flow_graph
from app.services.flow_service import create_flow, delete_flow, duplicate_flow, get_flow, get_flows, update_flow

router = APIRouter()
crud_router = APIRouter(tags=["flows-crud"])
TEMP_TENANT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


class FlowBuilderPayload(BaseModel):
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class FlowCreatePayload(BaseModel):
    name: str
    description: str | None = None
    is_active: bool = True
    trigger_type: str = "default"
    trigger_value: str | None = None
    keywords: str | None = None
    stop_words: str | None = None
    priority: int = 0


class FlowUpdatePayload(BaseModel):
    name: str | None = None
    description: str | None = None
    is_active: bool | None = None
    trigger_type: str | None = None
    trigger_value: str | None = None
    keywords: str | None = None
    stop_words: str | None = None
    priority: int | None = None
    version: int | None = None


class RestoreFlowVersionPayload(BaseModel):
    version_id: uuid.UUID


@router.get("/")
def list_flows(db: Session = Depends(get_db)):
    return [_serialize_flow(item) for item in get_flows(db=db, tenant_id=TEMP_TENANT_ID)]


@router.post("/")
def create_flow_route(payload: FlowCreatePayload, db: Session = Depends(get_db)):
    flow = create_flow(db=db, tenant_id=TEMP_TENANT_ID, data=payload.model_dump())
    db.commit()
    db.refresh(flow)
    return _serialize_flow(flow)


@router.put("/{flow_id}")
def update_flow_route(
    flow_id: uuid.UUID,
    payload: FlowUpdatePayload,
    db: Session = Depends(get_db),
):
    flow = update_flow(db=db, flow_id=flow_id, tenant_id=TEMP_TENANT_ID, data=payload.model_dump(exclude_unset=True))
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    db.commit()
    db.refresh(flow)
    return _serialize_flow(flow)


@router.delete("/{flow_id}")
def delete_flow_route(flow_id: uuid.UUID, db: Session = Depends(get_db)):
    deleted = delete_flow(db=db, flow_id=flow_id, tenant_id=TEMP_TENANT_ID)
    if not deleted:
        raise HTTPException(status_code=404, detail="Flow not found")
    db.commit()
    return {"status": "deleted"}


def _resolve_tenant_header(tenant_id: str | None) -> uuid.UUID:
    if not tenant_id:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is required")
    try:
        return uuid.UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="X-Tenant-ID header is invalid") from exc


def _serialize_flow(flow: Flow) -> dict[str, Any]:
    return {
        "id": str(flow.id),
        "tenant_id": str(flow.tenant_id),
        "name": flow.name,
        "description": flow.description,
        "is_active": flow.is_active,
        "trigger_type": flow.trigger_type,
        "trigger_value": flow.trigger_value,
        "keywords": flow.keywords,
        "stop_words": flow.stop_words,
        "priority": flow.priority,
        "version": flow.version,
        "current_version_id": str(flow.current_version_id) if flow.current_version_id else None,
        "created_at": flow.created_at.isoformat() if flow.created_at else None,
        "updated_at": flow.updated_at.isoformat() if flow.updated_at else None,
    }


def _serialize_flow_version(flow_version: FlowVersion, current_version_id: uuid.UUID | None) -> dict[str, Any]:
    return {
        "id": str(flow_version.id),
        "flow_id": str(flow_version.flow_id),
        "version": flow_version.version_number,
        "version_number": flow_version.version_number,
        "created_at": flow_version.created_at.isoformat() if flow_version.created_at else None,
        "is_current": bool(current_version_id and flow_version.id == current_version_id),
    }


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
    flow_id: str | None = None,
    db: Session = Depends(get_db),
):
    tenant = _resolve_tenant(db=db, tenant_id=tenant_id)
    if not tenant:
        return dict(_EMPTY_FLOW)

    graph = get_flow_graph(db=db, tenant_id=tenant.id, flow_id=flow_id or "default")
    return _normalize_flow_response(graph)


@router.post("/{tenant_id}")
def save_tenant_flow(
    tenant_id: str,
    payload: FlowBuilderPayload,
    flow_id: str | None = None,
    db: Session = Depends(get_db),
):
    tenant = _resolve_tenant(db=db, tenant_id=tenant_id)
    if not tenant:
        return dict(_EMPTY_FLOW)

    save_flow_graph(
        db=db,
        tenant_id=tenant.id,
        flow_id=flow_id or "default",
        nodes=payload.nodes or [],
        edges=payload.edges or [],
    )
    db.commit()

    graph = get_flow_graph(db=db, tenant_id=tenant.id, flow_id=flow_id or "default")
    return _normalize_flow_response(graph)


@crud_router.post("")
def create_tenant_flow(
    payload: FlowCreatePayload,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = create_flow(db=db, tenant_id=tenant_uuid, data=payload.model_dump())
    db.commit()
    db.refresh(flow)
    return _serialize_flow(flow)


@crud_router.get("")
def list_tenant_flows(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    return [_serialize_flow(item) for item in get_flows(db=db, tenant_id=tenant_uuid)]


@crud_router.get("/{flow_id}")
def get_tenant_flow_by_id(
    flow_id: uuid.UUID,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = get_flow(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    return _serialize_flow(flow)


@crud_router.get("/{flow_id}/analytics")
def get_tenant_flow_analytics(
    flow_id: uuid.UUID,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = get_flow(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    analytics = get_flow_analytics(db=db, tenant_id=tenant_uuid, flow_id=flow_id)
    print(f"[FLOW ANALYTICS] flow_id={flow_id} tenant_id={tenant_uuid} analytics={analytics}")
    return analytics


@crud_router.put("/{flow_id}")
def update_tenant_flow(
    flow_id: uuid.UUID,
    payload: FlowUpdatePayload,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = update_flow(db=db, flow_id=flow_id, tenant_id=tenant_uuid, data=payload.model_dump(exclude_unset=True))
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    db.commit()
    db.refresh(flow)
    return _serialize_flow(flow)


@crud_router.delete("/{flow_id}")
def delete_tenant_flow(
    flow_id: uuid.UUID,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    deleted = delete_flow(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
    if not deleted:
        raise HTTPException(status_code=404, detail="Flow not found")
    db.commit()
    return {"status": "deleted"}


@crud_router.post("/{flow_id}/duplicate")
def duplicate_tenant_flow(
    flow_id: uuid.UUID,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = duplicate_flow(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    db.commit()
    db.refresh(flow)
    return _serialize_flow(flow)


@crud_router.get("/{flow_id}/versions")
def list_tenant_flow_versions(
    flow_id: uuid.UUID,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = get_flow(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    versions = db.execute(
        select(FlowVersion)
        .where(FlowVersion.flow_id == flow.id)
        .order_by(FlowVersion.created_at.desc(), FlowVersion.version_number.desc())
    ).scalars().all()

    return [_serialize_flow_version(item, flow.current_version_id) for item in versions]


@crud_router.post("/{flow_id}/versions/restore")
def restore_tenant_flow_version(
    flow_id: uuid.UUID,
    payload: RestoreFlowVersionPayload,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = get_flow(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    flow_version = db.execute(
        select(FlowVersion).where(FlowVersion.id == payload.version_id, FlowVersion.flow_id == flow.id)
    ).scalars().first()
    if not flow_version:
        raise HTTPException(status_code=404, detail="Flow version not found")

    flow.current_version_id = flow_version.id
    flow.version = flow_version.version_number
    db.add(flow)
    db.commit()
    db.refresh(flow)

    return _serialize_flow(flow)


@crud_router.post("/{flow_id}/restore/{version_id}")
def restore_tenant_flow_version_by_path(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    payload = RestoreFlowVersionPayload(version_id=version_id)
    return restore_tenant_flow_version(flow_id=flow_id, payload=payload, x_tenant_id=x_tenant_id, db=db)
