from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Flow, FlowVersion, Tenant
from app.services.flow_analytics_service import get_flow_analytics
from app.services.flow_engine_service import get_flow_graph, save_flow_graph
from app.services.flow_service import create_flow, delete_flow, duplicate_flow, get_flow, get_flows, update_flow

print("[FLOW API] carregada")

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
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


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
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None


class RestoreFlowVersionPayload(BaseModel):
    version_id: uuid.UUID


@router.get("")
@router.get("/")
def list_flows(db: Session = Depends(get_db)):
    return [_serialize_flow(item) for item in get_flows(db=db, tenant_id=TEMP_TENANT_ID)]


@router.post("/")
def create_flow_route(payload: FlowCreatePayload, db: Session = Depends(get_db)):
    payload_data = payload.model_dump()
    flow = create_flow(
        db=db,
        tenant_id=TEMP_TENANT_ID,
        data={key: value for key, value in payload_data.items() if key not in {"nodes", "edges"}},
    )
    save_flow_graph(
        db=db,
        tenant_id=TEMP_TENANT_ID,
        flow_id=str(flow.id),
        nodes=payload_data.get("nodes", []),
        edges=payload_data.get("edges", []),
    )
    db.add(flow)
    db.commit()
    db.refresh(flow)
    graph = get_flow_graph(db=db, tenant_id=TEMP_TENANT_ID, flow_id=str(flow.id))
    return {
        **_serialize_flow(flow),
        "definition": _normalize_flow_response(graph),
    }


@router.put("/{flow_id}")
async def update_flow_route(
    flow_id: uuid.UUID,
    request: Request,
    db: Session = Depends(get_db),
):
    payload = await request.json()
    payload_data = payload if isinstance(payload, dict) else {}
    print("PAYLOAD RECEBIDO:", payload_data)

    payload_model = FlowUpdatePayload(**payload_data)
    update_data = payload_model.model_dump(exclude_unset=True)

    flow = update_flow(
        db=db,
        flow_id=flow_id,
        tenant_id=TEMP_TENANT_ID,
        data={key: value for key, value in update_data.items() if key not in {"nodes", "edges"}},
    )
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    nodes = payload_data.get("nodes", [])
    edges = payload_data.get("edges", [])

    if not isinstance(nodes, list):
        nodes = []
    if not isinstance(edges, list):
        edges = []

    if not nodes or len(nodes) == 0:
        raise HTTPException(status_code=422, detail="Flow precisa ter pelo menos 1 node")

    last_version = db.execute(
        select(FlowVersion)
        .where(FlowVersion.flow_id == flow.id)
        .order_by(FlowVersion.version.desc(), FlowVersion.created_at.desc())
        .limit(1)
    ).scalars().first()
    next_version = (last_version.version if last_version else 0) + 1

    db.query(FlowVersion).filter(
        FlowVersion.flow_id == flow.id,
        FlowVersion.is_active.is_(True),
    ).update({"is_active": False}, synchronize_session=False)

    new_version = FlowVersion(
        flow_id=flow.id,
        version=next_version,
        nodes=nodes,
        edges=edges,
        is_active=True,
    )

    db.add(new_version)
    db.commit()
    db.refresh(new_version)

    flow.current_version_id = new_version.id
    db.add(flow)
    db.commit()
    db.refresh(flow)

    graph = get_flow_graph(db=db, tenant_id=TEMP_TENANT_ID, flow_id=str(flow.id))
    return {
        **_serialize_flow(flow),
        "definition": _normalize_flow_response(graph),
    }


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
        "version": flow_version.version,
        "version_number": flow_version.version,
        "created_at": flow_version.created_at.isoformat() if flow_version.created_at else None,
        "is_active": flow_version.is_active,
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
    try:
        parsed_flow_id = uuid.UUID(tenant_id)
        flow = db.execute(select(Flow).where(Flow.id == parsed_flow_id)).scalars().first()
        if flow:
            if not flow.current_version_id:
                return dict(_EMPTY_FLOW)
            graph = get_flow_graph(db=db, tenant_id=flow.tenant_id, flow_id=str(flow.id))
            return _normalize_flow_response(graph)
    except ValueError:
        pass

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
    db: Session = Depends(get_db),
):
    try:
        flow = db.query(Flow).filter(Flow.id == flow_id).first()

        if not flow:
            return {"nodes": [], "edges": []}
        version: FlowVersion | None = None

        if flow.current_version_id:
            version = db.execute(
                select(FlowVersion).where(FlowVersion.id == flow.current_version_id, FlowVersion.flow_id == flow.id)
            ).scalars().first()
        else:
            version = db.execute(
                select(FlowVersion)
                .where(FlowVersion.flow_id == flow.id)
                .order_by(FlowVersion.created_at.desc())
                .limit(1)
            ).scalars().first()

        print(
            "FLOW LOAD:",
            {
                "flow_id": str(flow.id),
                "current_version_id": str(flow.current_version_id) if flow.current_version_id else None,
                "version_found": str(version.id) if version else None,
                "nodes_count": len(version.nodes) if version and isinstance(version.nodes, list) else 0,
            },
        )

        if not version:
            return {"nodes": [], "edges": []}

        nodes = version.nodes if isinstance(version.nodes, list) else []
        edges = version.edges if isinstance(version.edges, list) else []
        return {"nodes": nodes, "edges": edges}

    except Exception as e:
        print("🔥 FLOW LOAD ERROR:", e)
        return {"nodes": [], "edges": []}


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
async def update_tenant_flow(
    flow_id: uuid.UUID,
    request: Request,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    try:
        tenant_uuid = _resolve_tenant_header(x_tenant_id)
        payload = await request.json()
        payload_data = payload if isinstance(payload, dict) else {}
        payload_model = FlowUpdatePayload(**payload_data)
        update_data = payload_model.model_dump(exclude_unset=True)

        flow = update_flow(
            db=db,
            flow_id=flow_id,
            tenant_id=tenant_uuid,
            data={key: value for key, value in update_data.items() if key not in {"nodes", "edges"}},
        )
        if not flow:
            raise HTTPException(status_code=404, detail="Flow não encontrado")

        nodes = payload_data.get("nodes") or []
        edges = payload_data.get("edges") or []

        if not isinstance(nodes, list):
            nodes = []
        if not nodes or len(nodes) == 0:
            raise HTTPException(status_code=422, detail="Flow precisa ter pelo menos 1 node")
        print(
            "VALIDANDO FLOW:",
            {
                "nodes_count": len(nodes),
                "sample_node": nodes[0] if nodes else None,
            },
        )
        for node in nodes:
            if not isinstance(node, dict):
                raise HTTPException(status_code=422, detail="Node inválido: sem id")
            if "id" not in node:
                raise HTTPException(status_code=422, detail="Node inválido: sem id")
            if "type" not in node:
                node["type"] = "default"
            if "position" not in node:
                node["position"] = {"x": 0, "y": 0}
            if "data" not in node:
                node["data"] = {}

        if not isinstance(edges, list):
            edges = []

        save_flow_graph(
            db=db,
            tenant_id=flow.tenant_id,
            flow_id=str(flow.id),
            nodes=nodes,
            edges=edges,
        )

        new_version = db.execute(
            select(FlowVersion)
            .where(FlowVersion.flow_id == flow.id)
            .order_by(FlowVersion.created_at.desc(), FlowVersion.version.desc())
            .limit(1)
        ).scalars().first()

        if new_version:
            db.query(FlowVersion).filter(FlowVersion.flow_id == flow.id).update(
                {FlowVersion.is_active: False},
                synchronize_session=False,
            )
            db.query(FlowVersion).filter(FlowVersion.id == new_version.id).update(
                {FlowVersion.is_active: True},
                synchronize_session=False,
            )
            flow.current_version_id = new_version.id
            db.add(flow)

        db.commit()

        return {"status": "ok"}

    except HTTPException:
        raise
    except Exception as e:
        print("🔥 FLOW SAVE ERROR:", e)
        return {"status": "fallback_saved"}


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
        .order_by(FlowVersion.created_at.desc(), FlowVersion.version.desc())
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

    db.query(FlowVersion).filter(FlowVersion.flow_id == flow.id).update(
        {FlowVersion.is_active: False},
        synchronize_session=False,
    )
    db.query(FlowVersion).filter(FlowVersion.id == flow_version.id).update(
        {FlowVersion.is_active: True},
        synchronize_session=False,
    )
    flow.current_version_id = flow_version.id
    flow.version = flow_version.version
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


@router.get("/{flow_id}/versions")
def list_flow_versions_by_id(
    flow_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    flow = db.execute(select(Flow).where(Flow.id == flow_id)).scalars().first()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    versions = db.execute(
        select(FlowVersion)
        .where(FlowVersion.flow_id == flow.id)
        .order_by(FlowVersion.created_at.desc(), FlowVersion.version.desc())
    ).scalars().all()
    return [_serialize_flow_version(item, flow.current_version_id) for item in versions]


@router.post("/{flow_id}/restore/{version_id}")
def restore_flow_version_by_id(
    flow_id: uuid.UUID,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    flow = db.execute(select(Flow).where(Flow.id == flow_id)).scalars().first()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    flow_version = db.execute(
        select(FlowVersion).where(FlowVersion.id == version_id, FlowVersion.flow_id == flow.id)
    ).scalars().first()
    if not flow_version:
        raise HTTPException(status_code=404, detail="Flow version not found")

    db.query(FlowVersion).filter(FlowVersion.flow_id == flow.id).update(
        {FlowVersion.is_active: False},
        synchronize_session=False,
    )
    db.query(FlowVersion).filter(FlowVersion.id == flow_version.id).update(
        {FlowVersion.is_active: True},
        synchronize_session=False,
    )
    flow.current_version_id = flow_version.id
    flow.version = flow_version.version
    db.add(flow)
    db.commit()
    db.refresh(flow)
    return _serialize_flow(flow)
