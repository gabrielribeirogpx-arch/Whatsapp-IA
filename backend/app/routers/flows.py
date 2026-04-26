from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from app.schemas.flow import FlowUpdate
from sqlalchemy import String, cast, or_, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Flow, FlowVersion, Tenant
from app.services.flow_analytics_service import get_flow_analytics
from app.services.flow_engine_service import get_flow_graph, save_flow_graph
from app.services.flow_service import create_flow, delete_flow, duplicate_flow, get_flow, get_flows, update_flow

print("[FLOW API] carregada")

router = APIRouter()
crud_router = APIRouter(tags=["flows-crud"])

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


class RestoreFlowVersionPayload(BaseModel):
    version_id: uuid.UUID


class RenameFlowPayload(BaseModel):
    name: str


def parse_flow_id(flow_id: str):
    try:
        return uuid.UUID(flow_id)
    except Exception:
        return flow_id


def _resolve_flow_query(db: Session, flow_id: str):
    flow_id_parsed = parse_flow_id(flow_id)
    print("[FLOW DEBUG] flow_id recebido:", flow_id)
    print("[FLOW DEBUG] flow_id parseado:", flow_id_parsed)

    if isinstance(flow_id_parsed, uuid.UUID):
        return db.query(Flow).filter(Flow.id == flow_id_parsed), flow_id_parsed

    flow_id_text = str(flow_id_parsed).strip()
    fallback_flow_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"flow:{flow_id_text}")
    return (
        db.query(Flow).filter(
            or_(
                cast(Flow.id, String) == flow_id_text,
                Flow.id == fallback_flow_uuid,
            )
        ),
        fallback_flow_uuid,
    )


def _get_flow_by_identifier(db: Session, flow_id: str, tenant_id: uuid.UUID | None = None):
    query, _ = _resolve_flow_query(db=db, flow_id=flow_id)
    if tenant_id is not None:
        query = query.filter(Flow.tenant_id == tenant_id)
    return query.first()


def _get_valid_tenant(db: Session) -> Tenant:
    tenant = db.query(Tenant).order_by(Tenant.id.asc()).first()
    if not tenant:
        raise Exception("Nenhum tenant encontrado no banco")
    print("[FLOW DEBUG] Tenant usado:", tenant.id)
    return tenant


def _is_valid_flow(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> bool:
    del edges  # currently not mandatory for validity
    if not nodes or len(nodes) <= 1:
        return False
    return any(
        isinstance(node, dict)
        and isinstance(node.get("data"), dict)
        and bool(node.get("data", {}).get("isStart"))
        for node in nodes
    )


def _ensure_start_node(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not nodes:
        return nodes

    has_start = any(
        isinstance(node, dict)
        and isinstance(node.get("data"), dict)
        and bool(node.get("data", {}).get("isStart"))
        for node in nodes
    )
    if has_start:
        return nodes

    first_node = nodes[0] if isinstance(nodes[0], dict) else {}
    if not isinstance(first_node.get("data"), dict):
        first_node["data"] = {}

    first_node["data"]["isStart"] = True

    if not isinstance(first_node["data"].get("metadata"), dict):
        first_node["data"]["metadata"] = {}
    first_node["data"]["metadata"]["isStart"] = True

    print("FORÇANDO START NODE:", first_node.get("id"))
    return nodes


def _log_flow_version_blocked(flow_id: uuid.UUID, nodes_count: int) -> None:
    print(
        {
            "action": "FLOW_VERSION_BLOCKED",
            "reason": "invalid_payload",
            "flow_id": str(flow_id),
            "nodes": nodes_count,
        }
    )



@router.get("")
@router.get("/")
def list_flows(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant = _resolve_request_tenant(db=db, tenant_id_header=x_tenant_id)
    return [_serialize_flow(item) for item in get_flows(db=db, tenant_id=tenant.id)]


@router.post("/")
def create_flow_route(
    payload: FlowCreatePayload,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant = _resolve_request_tenant(db=db, tenant_id_header=x_tenant_id)
    payload_data = payload.model_dump()
    flow = create_flow(
        db=db,
        tenant_id=tenant.id,
        data={key: value for key, value in payload_data.items() if key not in {"nodes", "edges"}},
    )
    initial_nodes = payload_data.get("nodes", [])
    if not initial_nodes:
        initial_nodes = [_default_start_node()]
    initial_nodes = _ensure_start_node(initial_nodes)

    save_flow_graph(
        db=db,
        tenant_id=tenant.id,
        flow_id=str(flow.id),
        nodes=initial_nodes,
        edges=payload_data.get("edges", []),
    )
    db.add(flow)
    db.commit()
    db.refresh(flow)
    graph = get_flow_graph(db=db, tenant_id=tenant.id, flow_id=str(flow.id))
    return {
        **_serialize_flow(flow),
        "definition": _normalize_flow_response(graph),
    }


@router.put("/{flow_id}")
async def update_flow_route(
    flow_id: str,
    request: Request,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    try:
        payload = await request.json()
        payload_data = payload if isinstance(payload, dict) else {}

        raw_nodes = payload_data.get("nodes", [])
        raw_edges = payload_data.get("edges", [])

        print("PAYLOAD REAL:", payload_data)
        print("NODES RECEBIDOS:", raw_nodes)

        if not isinstance(raw_nodes, list):
            raw_nodes = []
        if not isinstance(raw_edges, list):
            raw_edges = []

        nodes = []
        for node in raw_nodes:
            normalized_node = node if isinstance(node, dict) else {}
            nodes.append(
                {
                    "id": str(normalized_node.get("id")),
                    "type": normalized_node.get("type") or "default",
                    "position": normalized_node.get("position") or {"x": 0, "y": 0},
                    "data": normalized_node.get("data") or {},
                }
            )
        nodes = _ensure_start_node(nodes)

        edges = raw_edges or []
        print("VALIDANDO FLOW:")
        print("nodes:", nodes)

        tenant = _resolve_request_tenant(db=db, tenant_id_header=x_tenant_id)
        flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant.id)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow não encontrado")

        print("[FLOW DEBUG] Flow encontrado ou criado:", flow.id)
        for key, value in payload_data.items():
            if key in {"name", "description", "is_active", "trigger_type", "trigger_value", "keywords", "stop_words", "priority", "version"}:
                setattr(flow, key, value)

        if not flow.id:
            raise Exception("Flow sem ID")

        persisted_nodes = flow.current_version.nodes if flow.current_version and isinstance(flow.current_version.nodes, list) else []
        persisted_edges = flow.current_version.edges if flow.current_version and isinstance(flow.current_version.edges, list) else []
        if not _is_valid_flow(nodes, edges):
            _log_flow_version_blocked(flow.id, len(nodes))
            if len(persisted_nodes) > len(nodes):
                print(
                    {
                        "action": "FLOW_VERSION_FALLBACK",
                        "reason": "payload_smaller_than_persisted",
                        "flow_id": str(flow.id),
                        "payload_nodes": len(nodes),
                        "persisted_nodes": len(persisted_nodes),
                    }
                )
                nodes = persisted_nodes
                edges = persisted_edges
            else:
                return {
                    "success": True,
                    "flow_id": flow.id,
                    "current_version_id": str(flow.current_version_id) if flow.current_version_id else None,
                    "version_blocked": True,
                }

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

        print("ANTES DE CRIAR VERSION")
        print("FLOW:", flow.id)
        print("NODES:", len(nodes))

        new_version = FlowVersion(
            flow_id=flow.id,
            version=next_version,
            nodes=nodes,
            edges=edges,
            is_active=True,
        )

        db.add(new_version)
        db.flush()
        flow.current_version_id = new_version.id

        print("ANTES DO COMMIT")
        db.commit()
        db.refresh(new_version)

        return {
            "success": True,
            "flow_id": flow.id,
        }
    except HTTPException:
        raise
    except Exception as e:
        import traceback

        print("❌ ERRO SALVANDO FLOW:")
        print(traceback.format_exc())

        db.rollback()

        return JSONResponse(
            status_code=500,
            content={
                "error": str(e),
                "trace": traceback.format_exc(),
            },
        )


@router.delete("/{flow_id}")
def delete_flow_route(
    flow_id: uuid.UUID,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant = _resolve_request_tenant(db=db, tenant_id_header=x_tenant_id)
    deleted = delete_flow(db=db, flow_id=flow_id, tenant_id=tenant.id)
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


def _resolve_request_tenant(db: Session, tenant_id_header: str | None) -> Tenant:
    if tenant_id_header:
        tenant = _resolve_tenant(db=db, tenant_id=tenant_id_header)
        if not tenant:
            raise HTTPException(status_code=404, detail="Tenant not found")
        return tenant
    return _get_valid_tenant(db=db)


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


def _default_start_node() -> dict[str, Any]:
    node_id = str(uuid.uuid4())
    return {
        "id": node_id,
        "type": "start",
        "position": {"x": 120, "y": 80},
        "data": {
            "label": "Início",
            "isStart": True,
            "metadata": {"isStart": True},
        },
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
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    resolved_request_tenant = _resolve_request_tenant(db=db, tenant_id_header=x_tenant_id)
    try:
        parsed_flow_id = uuid.UUID(tenant_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Flow não encontrado")

    flow = db.query(Flow).filter(Flow.id == parsed_flow_id, Flow.tenant_id == resolved_request_tenant.id).first()
    if not flow:
        raise HTTPException(status_code=404, detail="Flow não encontrado")

    graph = get_flow_graph(db=db, tenant_id=flow.tenant_id, flow_id=str(flow.id))
    return {
        "id": str(flow.id),
        "name": flow.name,
        "nodes": graph.get("nodes") or [],
        "edges": graph.get("edges") or [],
        "is_active": flow.is_active,
    }


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
        nodes=_ensure_start_node(payload.nodes or []),
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
    payload_data = payload.model_dump()
    flow = create_flow(db=db, tenant_id=tenant_uuid, data=payload_data)
    initial_nodes = payload_data.get("nodes", [])
    if not initial_nodes:
        initial_nodes = [_default_start_node()]
    initial_nodes = _ensure_start_node(initial_nodes)
    save_flow_graph(
        db=db,
        tenant_id=tenant_uuid,
        flow_id=str(flow.id),
        nodes=initial_nodes,
        edges=payload_data.get("edges", []),
    )
    db.commit()
    db.refresh(flow)
    return {
        **_serialize_flow(flow),
        "nodes": initial_nodes,
        "edges": payload_data.get("edges", []),
    }


@crud_router.get("")
def list_tenant_flows(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    return [_serialize_flow(item) for item in get_flows(db=db, tenant_id=tenant_uuid)]


@crud_router.get("/{flow_id}")
def get_tenant_flow_by_id(
    flow_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    parsed_flow_id = parse_flow_id(flow_id)
    if not isinstance(parsed_flow_id, uuid.UUID):
        raise HTTPException(status_code=404, detail="Flow não encontrado")

    flow = db.query(Flow).filter(Flow.id == parsed_flow_id, Flow.tenant_id == tenant_uuid).first()

    print("FLOW BUSCADO:", flow_id)
    print("FLOW ENCONTRADO:", str(flow.id) if flow else None)

    if not flow:
        raise HTTPException(status_code=404, detail="Flow não encontrado")

    graph = get_flow_graph(db=db, tenant_id=tenant_uuid, flow_id=str(flow.id))
    nodes = graph.get("nodes") or []
    edges = graph.get("edges") or []
    print("NODES:", nodes)

    return {
        "id": str(flow.id),
        "name": flow.name,
        "nodes": nodes,
        "edges": edges,
        "is_active": flow.is_active,
    }


@crud_router.get("/{flow_id}/analytics")
def get_tenant_flow_analytics(
    flow_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    analytics = get_flow_analytics(db=db, tenant_id=tenant_uuid, flow_id=flow_id)
    print(f"[FLOW ANALYTICS] flow_id={flow_id} tenant_id={tenant_uuid} analytics={analytics}")
    return analytics


@crud_router.put("/{flow_id}")
async def update_tenant_flow(
    flow_id: str,
    request: Request,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    try:
        tenant_uuid = _resolve_tenant_header(x_tenant_id)
        payload = await request.json()
        payload_data = payload if isinstance(payload, dict) else {}
        payload_model = FlowUpdate(**payload_data)
        print("FLOW RECEBIDO:", payload_model.model_dump())
        flow_update_fields = {
            "name",
            "description",
            "is_active",
            "trigger_type",
            "trigger_value",
            "keywords",
            "stop_words",
            "priority",
            "version",
        }

        flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow não encontrado")

        update_data = {key: value for key, value in payload_data.items() if key in flow_update_fields}
        for key, value in update_data.items():
            setattr(flow, key, value)

        nodes = []
        for node in payload_model.nodes or []:
            nodes.append(
                {
                    "id": str(node.id),
                    "type": node.type or "default",
                    "position": node.position or {"x": 0, "y": 0},
                    "data": node.data or {},
                }
            )
        edges = payload_model.edges or []
        print("VALIDANDO FLOW:")
        print("nodes:", nodes)

        persisted_nodes = flow.current_version.nodes if flow.current_version and isinstance(flow.current_version.nodes, list) else []
        persisted_edges = flow.current_version.edges if flow.current_version and isinstance(flow.current_version.edges, list) else []
        if not _is_valid_flow(nodes, edges):
            _log_flow_version_blocked(flow.id, len(nodes))
            if len(persisted_nodes) > len(nodes):
                print(
                    {
                        "action": "FLOW_VERSION_FALLBACK",
                        "reason": "payload_smaller_than_persisted",
                        "flow_id": str(flow.id),
                        "payload_nodes": len(nodes),
                        "persisted_nodes": len(persisted_nodes),
                    }
                )
                nodes = persisted_nodes
                edges = persisted_edges
            else:
                return {
                    "status": "ok",
                    "current_version_id": str(flow.current_version_id) if flow.current_version_id else None,
                    "version_blocked": True,
                }

        nova = FlowVersion(
            flow_id=flow.id,
            nodes=nodes,
            edges=edges,
            is_active=True,
        )
        db.add(nova)
        db.flush()

        db.query(FlowVersion).filter(
            FlowVersion.flow_id == flow.id,
            FlowVersion.id != nova.id,
        ).update(
            {"is_active": False},
            synchronize_session=False,
        )

        flow.current_version_id = nova.id
        db.commit()

        return {"status": "ok"}

    except HTTPException:
        raise
    except Exception as e:
        print("ERRO SALVAR FLOW:", str(e))
        raise HTTPException(status_code=500, detail="Erro interno")


@crud_router.delete("/{flow_id}")
def delete_tenant_flow(
    flow_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    if flow.name == "_default_visual_":
        raise HTTPException(status_code=400, detail="Default visual flow cannot be deleted")
    if flow.is_active:
        raise HTTPException(status_code=400, detail="Active flow cannot be deleted")
    db.delete(flow)
    db.commit()
    return {"status": "deleted"}


@crud_router.put("/{flow_id}/activate")
def activate_tenant_flow(
    flow_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow não encontrado")

    db.query(Flow).filter(
        Flow.tenant_id == tenant_uuid,
    ).update(
        {Flow.is_active: False},
        synchronize_session=False,
    )
    flow.is_active = True
    db.add(flow)
    db.commit()
    db.refresh(flow)
    return _serialize_flow(flow)


@crud_router.post("/deactivate")
def deactivate_tenant_flows(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)

    db.query(Flow).filter(
        Flow.tenant_id == tenant_uuid,
    ).update(
        {Flow.is_active: False},
        synchronize_session=False,
    )
    db.commit()
    return {"success": True}


@crud_router.put("/{flow_id}/rename")
def rename_tenant_flow(
    flow_id: str,
    payload: RenameFlowPayload,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    flow.name = payload.name
    db.add(flow)
    db.commit()
    db.refresh(flow)
    return _serialize_flow(flow)


@crud_router.post("/{flow_id}/duplicate")
def duplicate_tenant_flow(
    flow_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    source_flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
    if not source_flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    flow = duplicate_flow(db=db, flow_id=source_flow.id, tenant_id=tenant_uuid)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    db.commit()
    db.refresh(flow)
    return _serialize_flow(flow)


@crud_router.get("/{flow_id}/versions")
def list_tenant_flow_versions(
    flow_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
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
    flow_id: str,
    payload: RestoreFlowVersionPayload,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
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
    flow_id: str,
    version_id: uuid.UUID,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    payload = RestoreFlowVersionPayload(version_id=version_id)
    return restore_tenant_flow_version(flow_id=flow_id, payload=payload, x_tenant_id=x_tenant_id, db=db)


@router.get("/{flow_id}/versions")
def list_flow_versions_by_id(
    flow_id: str,
    db: Session = Depends(get_db),
):
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id)
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
    flow_id: str,
    version_id: uuid.UUID,
    db: Session = Depends(get_db),
):
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id)
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
