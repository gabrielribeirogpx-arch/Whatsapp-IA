from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from app.schemas.flow import FlowUpdate
from sqlalchemy import String, cast, inspect, or_, select
from sqlalchemy.orm import Session
from sqlalchemy.orm import load_only

from app.database import get_db
from app.models import Conversation, Flow, FlowVersion, Tenant
from app.services.flow_analytics_service import get_flow_analytics
from app.services.flow_engine_service import (
    get_flow_graph,
    invalidate_flow_runtime_cache,
    save_flow_graph,
    validate_flow_structure,
)
from app.services.flow_service import FlowService, create_flow, delete_flow, duplicate_flow, get_flow, get_flows, update_flow

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


class PublishFlowPayload(BaseModel):
    version_id: uuid.UUID | None = None


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
    query = query.filter(Flow.deleted_at.is_(None))
    return query.first()


def _get_valid_tenant(db: Session) -> Tenant:
    tenant = db.query(Tenant).order_by(Tenant.id.asc()).first()
    if not tenant:
        raise Exception("Nenhum tenant encontrado no banco")
    print("[FLOW DEBUG] Tenant usado:", tenant.id)
    return tenant


def validate_flow(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> tuple[bool, str | None]:
    return validate_flow_structure(nodes=nodes, edges=edges)


def _flow_versions_columns(db: Session) -> set[str]:
    return {column["name"] for column in inspect(db.bind).get_columns("flow_versions")}


def _flow_version_payload(db: Session, **values: Any) -> dict[str, Any]:
    columns = _flow_versions_columns(db)
    return {key: value for key, value in values.items() if key in columns}


def _flow_version_select(db: Session):
    columns = _flow_versions_columns(db)
    attrs = [getattr(FlowVersion, name) for name in ("id", "flow_id", "version", "nodes", "edges", "is_active", "created_at", "tenant_id", "snapshot") if name in columns]
    statement = select(FlowVersion)
    if attrs:
        statement = statement.options(load_only(*attrs))
    return statement


def _validate_nodes_by_type(nodes: list[dict[str, Any]]) -> None:
    for node in nodes:
        data = node.get("data", {})
        if not isinstance(data, dict):
            data = {}

        node_type = str(
            node.get("type")
            or data.get("type")
            or data.get("nodeType")
            or ""
        ).strip().lower()

        if node_type == "message":
            text = data.get("text")
            if isinstance(text, str):
                text = text.strip()
            if not text:
                raise HTTPException(status_code=400, detail="Mensagem sem texto")
        elif node_type == "condition":
            condition = data.get("condition")
            if isinstance(condition, str):
                condition = condition.strip()
            if not condition:
                data["condition"] = "default"
                print("[CONDITION FIX]: aplicado fallback")


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


def _block_invalid_flow_save() -> None:
    print("FLOW BLOQUEADO - inválido")
    raise Exception("Flow inválido - não salvar")


def _log_flow_version_blocked(flow_id: uuid.UUID, nodes_count: int) -> None:
    print(
        {
            "action": "FLOW_VERSION_BLOCKED",
            "reason": "invalid_payload",
            "flow_id": str(flow_id),
            "nodes": nodes_count,
        }
    )


def _validate_flow_payload(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    if len(nodes) < 2 or len(edges) < 1:
        raise HTTPException(status_code=400, detail="Fluxo inválido: mínimo de 2 nós e 1 conexão")

    start_nodes = [
        node
        for node in nodes
        if isinstance(node, dict) and bool((node.get("data") or {}).get("isStart"))
    ]
    if len(start_nodes) != 1:
        raise HTTPException(status_code=400, detail="Fluxo inválido: estrutura incompleta")

    node_ids = {str(node.get("id")) for node in nodes if node.get("id")}
    outgoing_count: dict[str, int] = {node_id: 0 for node_id in node_ids}
    incoming_count: dict[str, int] = {node_id: 0 for node_id in node_ids}
    outgoing_by_handle: dict[str, set[str]] = {node_id: set() for node_id in node_ids}

    for edge in edges:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in node_ids or target not in node_ids:
            raise HTTPException(status_code=400, detail="Edge inválida: origem/destino inexistente")
        outgoing_count[source] = outgoing_count.get(source, 0) + 1
        incoming_count[target] = incoming_count.get(target, 0) + 1
        source_handle = str(edge.get("sourceHandle") or (edge.get("data") or {}).get("sourceHandle") or "").lower()
        if source_handle:
            outgoing_by_handle[source].add(source_handle)

    unconnected_nodes = [
        node_id
        for node_id in node_ids
        if outgoing_count.get(node_id, 0) == 0 and incoming_count.get(node_id, 0) == 0
    ]
    if unconnected_nodes:
        raise HTTPException(
            status_code=400,
            detail="Fluxo inválido: existe nó sem conexão",
        )

    for node in nodes:
        node_id = str(node.get("id") or "")
        node_type = str(node.get("type") or "").lower()
        data = node.get("data") or {}
        if node_type == "condition":
            condition = str(data.get("condition") or "").strip()
            if not condition:
                raise HTTPException(status_code=400, detail="Condition vazio")
            if outgoing_count.get(node_id, 0) < 2:
                raise HTTPException(status_code=400, detail="Condition precisa de duas saídas (SIM e NÃO)")
            handles = outgoing_by_handle.get(node_id, set())
            if not {"true", "false"}.issubset(handles):
                raise HTTPException(status_code=400, detail="Condition precisa de saídas SIM e NÃO")
        elif node_type == "message":
            if outgoing_count.get(node_id, 0) < 1:
                raise HTTPException(status_code=400, detail="Message precisa de ao menos uma saída")


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
        print("[FLOW SAVE] nodes:", len(nodes))
        if not nodes or len(nodes) == 0:
            raise Exception("BLOCK SAVE: flow sem nodes")
        start_nodes = [n for n in nodes if n.get("data", {}).get("isStart") is True]
        if len(start_nodes) == 0:
            raise Exception("Flow precisa de um node inicial")
        if len(start_nodes) > 1:
            raise Exception("Flow só pode ter um node inicial")
        print("VALIDANDO FLOW:")
        print("nodes:", nodes)
        _validate_nodes_by_type(nodes)

        tenant = _resolve_request_tenant(db=db, tenant_id_header=x_tenant_id)
        flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant.id)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow não encontrado")

        print("[FLOW DEBUG] Flow encontrado ou criado:", flow.id)
        for key, value in payload_data.items():
            if key in {"name", "description", "is_active", "trigger_type", "trigger_value", "keywords", "stop_words", "priority", "version"}:
                setattr(flow, key, value)
        if flow.is_active:
            db.query(Flow).filter(
                Flow.tenant_id == tenant.id,
                Flow.id != flow.id,
            ).update({Flow.is_active: False}, synchronize_session=False)

        if not flow.id:
            raise Exception("Flow sem ID")

        persisted_nodes = flow.current_version.nodes if flow.current_version and isinstance(flow.current_version.nodes, list) else []
        print("[FLOW SAVE ATTEMPT]", {"flow_id": str(flow.id), "nodes": len(nodes), "edges": len(edges)})
        if len(persisted_nodes) > 1 and len(nodes) <= 1:
            print("[FLOW SAVE BLOCKED]", {"flow_id": str(flow.id), "reason": "possible_accidental_overwrite"})
            return JSONResponse(
                status_code=400,
                content={"error": "payload inválido: possível sobrescrita acidental"},
            )
        _validate_flow_payload(nodes, edges)
        valid, error = validate_flow(nodes, edges)
        print("[FLOW VALID]:", valid)
        if not valid:
            print(f"[FLOW BLOCKED] {error}")
            _log_flow_version_blocked(flow.id, len(nodes))
            if persisted_nodes and not raw_nodes and not raw_edges:
                print(
                    {
                        "action": "FLOW_VERSION_BLOCKED",
                        "reason": "empty_payload_would_overwrite_existing",
                        "flow_id": str(flow.id),
                    }
                )
            return JSONResponse(status_code=400, content={"error": error or "Flow inválido"})

        last_version = db.execute(
            _flow_version_select(db)
            .where(FlowVersion.flow_id == flow.id)
            .order_by(FlowVersion.version.desc(), FlowVersion.created_at.desc())
            .limit(1)
        ).scalars().first()
        next_version = (last_version.version if last_version else 0) + 1

        if flow.current_version:
            backup_version = FlowVersion(**_flow_version_payload(
                db,
                flow_id=flow.id,
                tenant_id=tenant.id,
                version=next_version,
                snapshot={
                    "nodes": flow.current_version.nodes or [],
                    "edges": flow.current_version.edges or [],
                },
                nodes=flow.current_version.nodes or [],
                edges=flow.current_version.edges or [],
                is_active=False,
            is_published=False,
            ))
            db.add(backup_version)
            db.flush()
            print("[FLOW VERSION CREATED]", {"flow_id": str(flow.id), "version_id": str(backup_version.id), "type": "snapshot"})
            next_version += 1


        print("ANTES DE CRIAR VERSION")
        print("FLOW:", flow.id)
        print("NODES:", len(nodes))

        new_version = FlowVersion(**_flow_version_payload(
            db,
            flow_id=flow.id,
            tenant_id=tenant.id,
            version=next_version,
            snapshot={"nodes": nodes, "edges": edges},
            nodes=nodes,
            edges=edges,
            is_active=False,
            is_published=False,
        ))

        db.add(new_version)
        db.flush()
        flow.current_version_id = new_version.id
        invalidate_flow_runtime_cache(flow.id)
        if flow.is_active:
            print("[FLOW ACTIVE]:", flow.id)

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


def _rename_flow_name(
    *,
    db: Session,
    flow_id: str,
    payload: RenameFlowPayload,
    tenant_id: uuid.UUID | None,
) -> dict[str, Any]:
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant_id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    normalized_name = payload.name.strip()
    if not normalized_name:
        raise HTTPException(status_code=400, detail="Name is required")

    flow.name = normalized_name
    db.add(flow)
    db.commit()
    db.refresh(flow)
    return _serialize_flow(flow)


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


def _normalize_flow_response(payload: dict[str, Any] | None) -> dict[str, Any]:
    if not payload:
        return dict(_EMPTY_FLOW)

    nodes = payload.get("nodes")
    edges = payload.get("edges")
    return {
        "flow_id": payload.get("flow_id"),
        "version_id": payload.get("version_id"),
        "source": payload.get("source"),
        "nodes": nodes if isinstance(nodes, list) else [],
        "edges": edges if isinstance(edges, list) else [],
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
        "version_id": graph.get("version_id"),
        "source": graph.get("source"),
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

    normalized_nodes = _ensure_start_node(payload.nodes or [])
    normalized_edges = payload.edges or []
    print("[FLOW SAVE] nodes:", len(normalized_nodes))
    if not normalized_nodes or len(normalized_nodes) == 0:
        raise HTTPException(status_code=400, detail="BLOCK SAVE: flow sem nodes")
    start_nodes = [n for n in normalized_nodes if n.get("data", {}).get("isStart") is True]
    if len(start_nodes) == 0:
        raise HTTPException(status_code=400, detail="Flow precisa de um node inicial")
    if len(start_nodes) > 1:
        raise HTTPException(status_code=400, detail="Flow só pode ter um node inicial")
    valid, error = validate_flow(normalized_nodes, normalized_edges)
    print("[FLOW VALID]:", valid)
    if not valid:
        print(f"[FLOW BLOCKED] {error}")
        raise HTTPException(status_code=400, detail=error or "Flow inválido")

    existing_graph = get_flow_graph(db=db, tenant_id=tenant.id, flow_id=flow_id or "default")
    existing_nodes = existing_graph.get("nodes") if isinstance(existing_graph, dict) else []
    if existing_nodes and not (payload.nodes or []) and not (payload.edges or []):
        print(
            {
                "action": "FLOW_VERSION_BLOCKED",
                "reason": "empty_payload_would_overwrite_existing",
                "flow_id": flow_id or "default",
            }
        )
        _block_invalid_flow_save()

    save_flow_graph(
        db=db,
        tenant_id=tenant.id,
        flow_id=flow_id or "default",
        nodes=normalized_nodes,
        edges=normalized_edges,
    )
    db.commit()

    graph = get_flow_graph(db=db, tenant_id=tenant.id, flow_id=flow_id or "default")
    return _normalize_flow_response(graph)


@crud_router.post("")
def create_tenant_flow(
    payload: FlowCreatePayload,
    request: Request,
    db: Session = Depends(get_db),
):
    tenant_uuid = request.state.tenant_id
    if not tenant_uuid:
        raise HTTPException(status_code=400, detail="Tenant obrigatório")
    payload_data = payload.model_dump()
    if not isinstance(payload_data.get("nodes"), list) or not isinstance(payload_data.get("edges"), list):
        raise HTTPException(status_code=400, detail="Payload inválido")
    _validate_flow_payload(payload_data.get("nodes") or [], payload_data.get("edges") or [])
    print(
        {
            "tenant": str(tenant_uuid),
            "nodes_count": len(payload_data.get("nodes") or []),
            "edges_count": len(payload_data.get("edges") or []),
        }
    )
    flow_service = FlowService(db)
    flow = flow_service.create_flow(tenant_id=tenant_uuid, data=payload_data)
    initial_nodes = payload_data.get("nodes", [])
    if not initial_nodes:
        initial_nodes = [_default_start_node()]
    initial_nodes = _ensure_start_node(initial_nodes)
    initial_edges = payload_data.get("edges", [])
    first_version = flow_service.create_version(flow=flow, tenant_id=tenant_uuid, nodes=initial_nodes, edges=initial_edges)
    db.commit()
    db.refresh(flow)
    return {
        **_serialize_flow(flow),
        "version": flow.version,
        "nodes": flow.current_version.nodes if flow.current_version else [],
        "edges": flow.current_version.edges if flow.current_version else [],
    }


@crud_router.get("")
def list_tenant_flows(
    request: Request,
    db: Session = Depends(get_db),
):
    tenant_uuid = request.state.tenant_id
    if not tenant_uuid:
        raise HTTPException(status_code=400, detail="Tenant obrigatório")
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

    flow = db.query(Flow).filter(
        Flow.id == parsed_flow_id,
        Flow.tenant_id == tenant_uuid,
        Flow.deleted_at.is_(None),
    ).first()
    print("[FLOW GET DEBUG]", {"tenant_id": str(tenant_uuid), "flow_id": flow_id, "query_result": str(flow.id) if flow else None})

    if not flow:
        print("[FLOW GET ERROR]", {"tenant_id": str(tenant_uuid), "flow_id": flow_id, "reason": "flow_not_found"})
        raise HTTPException(status_code=404, detail="Flow não encontrado")

    resolved = FlowService(db).get_flow_with_version(flow)
    nodes = resolved["nodes"]
    edges = resolved["edges"]
    version = resolved["version"]
    print("[FLOW LOAD]", {"flow_id": str(flow.id), "version": version, "nodes_count": len(nodes)})

    return {
        "id": str(flow.id),
        "name": flow.name,
        "version": version,
        "nodes": nodes,
        "edges": edges,
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
    db: Session = Depends(get_db),
):
    try:
        tenant_uuid = request.state.tenant_id
        if not tenant_uuid:
            raise HTTPException(status_code=400, detail="Tenant obrigatório")
        payload = await request.json()
        payload_data = payload if isinstance(payload, dict) else {}
        if not isinstance(payload_data.get("nodes"), list) or not isinstance(payload_data.get("edges"), list):
            raise HTTPException(status_code=400, detail="Payload inválido")
        print("[FLOW SAVE]", {"tenant": str(tenant_uuid), "nodes_count": len(payload_data.get("nodes") or []), "edges_count": len(payload_data.get("edges") or [])})
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
        if flow.is_active:
            db.query(Flow).filter(
                Flow.tenant_id == tenant_uuid,
                Flow.id != flow.id,
            ).update({Flow.is_active: False}, synchronize_session=False)

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
        nodes = _ensure_start_node(nodes)
        edges = payload_model.edges or []
        edges_json = [
            {
                "id": getattr(edge, "id", None),
                "source": getattr(edge, "source", None),
                "target": getattr(edge, "target", None),
            }
            for edge in edges
        ]
        nodes_json = nodes
        print("[FLOW SAVE OK]")
        print("nodes:", len(nodes_json))
        print("edges:", len(edges_json))
        print("VALIDANDO FLOW:")
        print("nodes:", nodes)
        _validate_nodes_by_type(nodes)

        persisted_nodes = flow.current_version.nodes if flow.current_version and isinstance(flow.current_version.nodes, list) else []
        if len(persisted_nodes) > 2 and len(nodes) <= 1:
            raise HTTPException(
                status_code=400,
                detail="Bloqueado: tentativa de sobrescrever fluxo válido com fluxo vazio",
            )
        _validate_flow_payload(nodes_json, edges_json)
        valid, error = validate_flow(nodes_json, edges_json)
        print("[FLOW VALID]:", valid)
        if not valid:
            print(f"[FLOW BLOCKED] {error}")
            _log_flow_version_blocked(flow.id, len(nodes))
            incoming_nodes = payload_model.nodes or []
            incoming_edges = payload_model.edges or []
            if persisted_nodes and not incoming_nodes and not incoming_edges:
                print(
                    {
                        "action": "FLOW_VERSION_BLOCKED",
                        "reason": "empty_payload_would_overwrite_existing",
                        "flow_id": str(flow.id),
                    }
                )
            raise HTTPException(status_code=400, detail=error or "Flow inválido")

        flow_service = FlowService(db)
        nova = flow_service.create_version(flow=flow, tenant_id=tenant_uuid, nodes=nodes_json, edges=edges_json)

        db.query(FlowVersion).filter(
            FlowVersion.flow_id == flow.id,
            FlowVersion.id != nova.id,
        ).update(
            {"is_active": False, "is_published": False},
            synchronize_session=False,
        )

        invalidate_flow_runtime_cache(flow.id)
        if flow.is_active:
            print("[FLOW ACTIVE]:", flow.id)
        db.commit()

        print("[FLOW SAVE]", {"tenant_id": str(tenant_uuid), "nodes_count": len(nodes_json), "edges_count": len(edges_json), "version": flow.version})
        db.refresh(flow)
        resolved = flow_service.get_flow_with_version(flow)
        return {"id": str(flow.id), "name": flow.name, "version": flow.version, "nodes": resolved["nodes"], "edges": resolved["edges"]}

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
    if flow.name == "default_visual":
        raise HTTPException(status_code=400, detail="Default visual flow cannot be deleted")
    if flow.is_active:
        raise HTTPException(status_code=400, detail="Active flow cannot be deleted")
    db.query(Conversation).filter(
        Conversation.tenant_id == tenant_uuid,
        Conversation.current_flow_id == flow.id,
    ).update(
        {Conversation.current_flow_id: None},
        synchronize_session=False,
    )
    flow.deleted_at = datetime.utcnow()
    db.commit()
    return {"success": True}


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
    return _rename_flow_name(
        db=db,
        flow_id=flow_id,
        payload=payload,
        tenant_id=tenant_uuid,
    )


@router.put("/{flow_id}/rename")
def rename_flow_route(
    flow_id: str,
    payload: RenameFlowPayload,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant = _resolve_request_tenant(db=db, tenant_id_header=x_tenant_id)
    return _rename_flow_name(
        db=db,
        flow_id=flow_id,
        payload=payload,
        tenant_id=tenant.id,
    )


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
        _flow_version_select(db)
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

    if payload.version_id:
        flow_version = db.execute(
            _flow_version_select(db).where(FlowVersion.id == payload.version_id, FlowVersion.flow_id == flow.id)
        ).scalars().first()
    else:
        flow_version = db.execute(
            _flow_version_select(db).where(FlowVersion.flow_id == flow.id).order_by(FlowVersion.version.desc()).limit(1)
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
    invalidate_flow_runtime_cache(flow.id)
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
        _flow_version_select(db)
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
        _flow_version_select(db).where(FlowVersion.id == version_id, FlowVersion.flow_id == flow.id)
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
    invalidate_flow_runtime_cache(flow.id)
    db.add(flow)
    db.commit()
    db.refresh(flow)
    return _serialize_flow(flow)


@crud_router.post("/{flow_id}/publish")
def publish_tenant_flow_version(
    flow_id: str,
    payload: PublishFlowPayload,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    if payload.version_id:
        flow_version = db.execute(
            _flow_version_select(db).where(FlowVersion.id == payload.version_id, FlowVersion.flow_id == flow.id)
        ).scalars().first()
    else:
        flow_version = db.execute(
            _flow_version_select(db).where(FlowVersion.flow_id == flow.id).order_by(FlowVersion.version.desc()).limit(1)
        ).scalars().first()
    if not flow_version:
        raise HTTPException(status_code=404, detail="Flow version not found")

    nodes = flow_version.nodes if isinstance(flow_version.nodes, list) else []
    edges = flow_version.edges if isinstance(flow_version.edges, list) else []
    valid, error = validate_flow_structure(nodes=nodes, edges=edges)
    if not valid:
        raise HTTPException(status_code=400, detail=error or "Flow inválido")

    FlowService(db).publish_version(flow=flow, flow_version=flow_version)
    invalidate_flow_runtime_cache(flow.id)
    db.commit()
    db.refresh(flow)
    print(
        {
            "action": "FLOW_PUBLISHED",
            "flow_id": str(flow.id),
            "version_id": str(flow_version.id),
        }
    )
    return {
        "success": True,
        "flow_id": str(flow.id),
        "published_version_id": str(flow.published_version_id),
    }
