from __future__ import annotations

import uuid
import logging
import asyncio
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
from app.models import Conversation, Flow, FlowSession, FlowVersion, Tenant
from app.services.flow_analytics_service import get_flow_analytics
from app.services.flow_engine_service import (
    get_flow_graph,
    invalidate_flow_runtime_cache,
    save_flow_graph,
    validate_flow as validate_flow_definition,
    validate_flow_graph,
)
from app.services.flow_service import FlowService, create_flow, delete_flow, duplicate_flow, get_flow, get_flows, update_flow

router = APIRouter()
crud_router = APIRouter(tags=["flows-crud"])
logger = logging.getLogger(__name__)
logger.info("[FLOW API] carregada")

class FlowBuilderPayload(BaseModel):
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class FlowCreatePayload(BaseModel):
    name: str = "Novo fluxo"
    description: str | None = None
    is_active: bool = True
    trigger_type: str = "default"
    trigger_value: str | None = None
    keywords: str | None = None
    stop_words: str | None = None
    priority: int = 0
    status: str = "draft"
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)


class RestoreFlowVersionPayload(BaseModel):
    version_id: uuid.UUID


class PublishFlowPayload(BaseModel):
    version_id: uuid.UUID | None = None


class RenameFlowPayload(BaseModel):
    name: str


class DeleteFlowResponse(BaseModel):
    success: bool = True
    mode: str = Field(
        default="hard_delete",
        description="Modo de remoção aplicado: hard_delete (remoção física) ou soft_delete (marcado como deletado).",
    )


class CanonicalFlowVersionResponse(BaseModel):
    flow_id: str
    version_id: str | None = None
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    version: int | None = None


class FlowVersionResponse(CanonicalFlowVersionResponse):
    id: str
    definition: dict[str, Any]
    is_active: bool
    name: str | None = None


def parse_flow_id(flow_id: str):
    try:
        return uuid.UUID(flow_id)
    except Exception:
        return flow_id


def _resolve_flow_query(db: Session, flow_id: str):
    flow_id_parsed = parse_flow_id(flow_id)
    logger.info("[FLOW DEBUG] flow_id recebido: %s", flow_id)
    logger.info("[FLOW DEBUG] flow_id parseado: %s", flow_id_parsed)

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
    query = query.filter(Flow.deleted_at.is_(None), Flow.is_deleted.is_(False))
    return query.first()




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
                logger.info("[CONDITION FIX]: aplicado fallback")


def _ensure_start_node(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not nodes:
        return [
            {
                "id": "start",
                "type": "start",
                "data": {"isStart": True},
                "position": {"x": 0, "y": 0},
            }
        ]

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

    logger.info("FORÇANDO START NODE: %s", first_node.get("id"))
    return nodes


def _normalize_flow_creation_graph(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    normalized_nodes = _ensure_start_node(nodes or [])
    normalized_edges = edges or []
    if not nodes:
        normalized_edges = []
    return normalized_nodes, normalized_edges


def _block_invalid_flow_save() -> None:
    logger.error("FLOW BLOQUEADO - inválido")
    raise Exception("Flow inválido - não salvar")


def _log_flow_version_blocked(flow_id: uuid.UUID, nodes_count: int) -> None:
    logger.error("[FLOW VERSION BLOCKED] flow_id=%s nodes=%s", str(flow_id), nodes_count)


def validate_flow_payload_or_400(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if not isinstance(nodes, list):
        raise HTTPException(status_code=400, detail="VALIDATION_ERROR: NODES_REQUIRED")
    if not isinstance(edges, list):
        edges = []

    if not nodes:
        normalized_nodes, normalized_edges = _normalize_flow_creation_graph(nodes, edges)
        logger.warning(
            "[FLOW VALIDATION] payload vazio normalizado para compatibilidade create: nodes=%s edges=%s",
            len(normalized_nodes),
            len(normalized_edges),
        )
        return normalized_nodes, normalized_edges

    start_nodes = [
        node
        for node in nodes
        if isinstance(node, dict) and bool((node.get("data") or {}).get("isStart"))
    ]
    if len(start_nodes) != 1:
        raise HTTPException(status_code=400, detail="VALIDATION_ERROR: SINGLE_START_NODE_REQUIRED")

    node_ids = {str(node.get("id")) for node in nodes if isinstance(node, dict) and node.get("id")}
    if len(node_ids) != len(nodes):
        raise HTTPException(status_code=400, detail="VALIDATION_ERROR: NODE_ID_REQUIRED")

    outgoing_count: dict[str, int] = {node_id: 0 for node_id in node_ids}
    incoming_count: dict[str, int] = {node_id: 0 for node_id in node_ids}
    outgoing_by_handle: dict[str, set[str]] = {node_id: set() for node_id in node_ids}

    for edge in edges or []:
        source = str(edge.get("source") or "")
        target = str(edge.get("target") or "")
        if source not in node_ids or target not in node_ids:
            raise HTTPException(status_code=400, detail="VALIDATION_ERROR: EDGE_REFERENCE_NOT_FOUND")
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
        logger.warning(
            "[FLOW VALIDATION] ORPHAN_NODE_FOUND ignorado para não bloquear criação inicial: %s",
            unconnected_nodes,
        )

    
    for node in nodes:
        node_id = str(node.get("id") or "")
        node_type = str(node.get("type") or "").lower()
        data = node.get("data") or {}
        if node_type == "condition":
            condition = str(data.get("condition") or "").strip()
            if not condition:
                raise HTTPException(status_code=400, detail="VALIDATION_ERROR: CONDITION_EMPTY")
            if outgoing_count.get(node_id, 0) < 2:
                raise HTTPException(status_code=400, detail="VALIDATION_ERROR: CONDITION_REQUIRES_TWO_OUTPUTS")
            handles = outgoing_by_handle.get(node_id, set())
            if not {"true", "false"}.issubset(handles):
                raise HTTPException(status_code=400, detail="VALIDATION_ERROR: CONDITION_REQUIRES_TRUE_FALSE")
        elif node_type == "message" and outgoing_count.get(node_id, 0) < 1:
            raise HTTPException(status_code=400, detail="VALIDATION_ERROR: MESSAGE_REQUIRES_OUTPUT")

    validation = validate_flow_graph(nodes, edges or [], mode="draft")
    if not validation["valid"]:
        logger.warning(
            "[FLOW VALIDATION] FLOW_INVALID/INVALID_GRAPH ignorado para não bloquear requisição: %s",
            validation["errors"][0] if validation["errors"] else "VALIDATION_ERROR: FLOW_INVALID",
        )
    return nodes, edges


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
    payload: FlowCreatePayload | None = None,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant = _resolve_request_tenant(db=db, tenant_id_header=x_tenant_id)
    payload_data = payload.model_dump(exclude_unset=True) if payload else {}
    incoming_name = payload_data.get("name")
    normalized_name = incoming_name.strip() if isinstance(incoming_name, str) else ""
    if not normalized_name:
        normalized_name = "Novo fluxo"
    flow = create_flow(
        db=db,
        tenant_id=tenant.id,
        data={
            **{key: value for key, value in payload_data.items() if key not in {"name", "nodes", "edges"}},
            "name": normalized_name,
        },
    )
    initial_nodes = payload_data.get("nodes") if isinstance(payload_data.get("nodes"), list) else [_default_start_node()]
    initial_edges = payload_data.get("edges") if isinstance(payload_data.get("edges"), list) else []
    initial_nodes = _ensure_start_node(initial_nodes)

    save_flow_graph(
        db=db,
        tenant_id=tenant.id,
        flow_id=str(flow.id),
        nodes=initial_nodes,
        edges=initial_edges,
    )
    db.add(flow)
    db.commit()
    db.refresh(flow)
    graph = get_flow_graph(db=db, tenant_id=tenant.id, flow_id=str(flow.id))
    normalized_definition = _normalize_flow_response(graph)
    validation = validate_flow_definition({"nodes": initial_nodes, "edges": initial_edges}, mode="draft")
    return {
        **_serialize_flow(flow),
        "definition": normalized_definition,
        "validation": validation,
    }


@crud_router.put("/{flow_id}")
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

        logger.info("PAYLOAD REAL: %s", payload_data)
        logger.info("NODES RECEBIDOS: %s", raw_nodes)

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
        logger.info("[FLOW SAVE] nodes: %s", len(nodes))
        if not nodes or len(nodes) == 0:
            raise Exception("BLOCK SAVE: flow sem nodes")
        start_nodes = [n for n in nodes if n.get("data", {}).get("isStart") is True]
        if len(start_nodes) == 0:
            raise Exception("Flow precisa de um node inicial")
        if len(start_nodes) > 1:
            raise Exception("Flow só pode ter um node inicial")
        logger.info("VALIDANDO FLOW: nodes=%s", nodes)
        
        tenant = _resolve_request_tenant(db=db, tenant_id_header=x_tenant_id)
        flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant.id)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow não encontrado")

        logger.info("[FLOW DEBUG] Flow encontrado ou criado: %s", flow.id)
        for key, value in payload_data.items():
            if key in {"name", "description", "is_active", "trigger_type", "trigger_value", "keywords", "stop_words", "priority", "version", "status"}:
                setattr(flow, key, value)
        if flow.is_active:
            db.query(Flow).filter(
                Flow.tenant_id == tenant.id,
                Flow.id != flow.id,
            ).update({Flow.is_active: False}, synchronize_session=False)

        if not flow.id:
            raise Exception("Flow sem ID")

        persisted_nodes = flow.current_version.nodes if flow.current_version and isinstance(flow.current_version.nodes, list) else []
        logger.info("[FLOW SAVE ATTEMPT] flow_id=%s nodes=%s edges=%s", str(flow.id), len(nodes), len(edges))
        if len(persisted_nodes) > 1 and len(nodes) <= 1:
            logger.error("[FLOW SAVE BLOCKED] flow_id=%s reason=possible_accidental_overwrite", str(flow.id))
            return JSONResponse(
                status_code=400,
                content={"error": "payload inválido: possível sobrescrita acidental"},
            )
        validation = validate_flow_definition({"nodes": nodes, "edges": edges}, mode="draft")

        last_version = db.execute(
            _flow_version_select(db)
            .where(FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant.id)
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
            logger.info("[FLOW VERSION CREATE] tenant_id=%s flow_id=%s version_id=%s request_id=%s", str(tenant.id), str(flow.id), str(backup_version.id), None)
            next_version += 1


        logger.info("ANTES DE CRIAR VERSION flow=%s nodes=%s", flow.id, len(nodes))

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
            logger.info("[FLOW ACTIVE]: %s", flow.id)

        logger.info("ANTES DO COMMIT")
        db.commit()
        db.refresh(new_version)

        return {"flow": _serialize_flow(flow), "validation": validation}
    except HTTPException:
        raise
    except Exception as e:
        import traceback

        logger.exception("[FLOW SAVE ERROR] exception while saving flow")

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
        raise HTTPException(status_code=403, detail="X-Tenant-ID header is required")
    try:
        return uuid.UUID(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="X-Tenant-ID header is invalid") from exc


def _resolve_request_tenant(db: Session, tenant_id_header: str | None) -> Tenant:
    tenant_uuid = _resolve_tenant_header(tenant_id_header)
    tenant = db.execute(select(Tenant).where(Tenant.id == tenant_uuid)).scalars().first()
    if not tenant:
        raise HTTPException(status_code=403, detail="Tenant not found")
    return tenant


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
        "status": flow.status,
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




def _serialize_flow_version_response(
    *,
    flow: Flow,
    nodes: list[dict[str, Any]] | None,
    edges: list[dict[str, Any]] | None,
    version_id: uuid.UUID | str | None,
    version: int | None = None,
) -> dict[str, Any]:
    normalized_nodes = nodes if isinstance(nodes, list) else []
    normalized_edges = edges if isinstance(edges, list) else []
    version_value = version if version is not None else flow.version
    serialized_version_id = str(version_id) if version_id else None
    canonical = {
        "flow_id": str(flow.id),
        "version_id": serialized_version_id,
        "nodes": normalized_nodes,
        "edges": normalized_edges,
        "version": version_value,
    }
    return {
        **canonical,
        "id": str(flow.id),
        "definition": canonical,
        "is_active": flow.is_active,
        "name": flow.name,
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


@router.get("/tenant/{tenant_id}")
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

    flow = db.query(Flow).filter(
        Flow.id == parsed_flow_id,
        Flow.tenant_id == resolved_request_tenant.id,
        Flow.deleted_at.is_(None),
        Flow.is_deleted.is_(False),
    ).first()
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


@router.post("/tenant/{tenant_id}")
def save_tenant_flow(
    tenant_id: str,
    payload: FlowBuilderPayload,
    flow_id: str | None = None,
    db: Session = Depends(get_db),
):
    tenant = _resolve_tenant(db=db, tenant_id=tenant_id)
    if not tenant:
        return dict(_EMPTY_FLOW)

    normalized_nodes = payload.nodes or []
    normalized_edges = payload.edges or []
    logger.info("[FLOW SAVE] nodes: %s", len(normalized_nodes))
    validate_flow_payload_or_400(normalized_nodes, normalized_edges)

    existing_graph = get_flow_graph(db=db, tenant_id=tenant.id, flow_id=flow_id or "default")
    existing_nodes = existing_graph.get("nodes") if isinstance(existing_graph, dict) else []
    if existing_nodes and not (payload.nodes or []) and not (payload.edges or []):
        logger.error("[FLOW VERSION BLOCKED] flow_id=%s reason=empty_payload_would_overwrite_existing", flow_id or "default")
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


@crud_router.post("", response_model=FlowVersionResponse)
def create_tenant_flow(
    payload: FlowCreatePayload,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    payload_data = payload.model_dump()
    logger.info("[FLOW CREATE PAYLOAD] %s", payload_data)
    logger.info("[FLOW CREATE NODES] %s", payload_data.get("nodes"))
    logger.info("[FLOW CREATE EDGES] %s", payload_data.get("edges"))
    if not isinstance(payload_data.get("nodes"), list) or not isinstance(payload_data.get("edges"), list):
        raise HTTPException(status_code=400, detail="Payload inválido")

    initial_nodes = payload_data.get("nodes") or []
    initial_edges = payload_data.get("edges") or []
    logger.info("[FLOW CREATE INPUT] tenant_id=%s nodes_count=%s edges_count=%s", str(tenant_uuid), len(initial_nodes), len(initial_edges))
    # TEMP DEBUG
    print(
        "CREATE FLOW:",
        {
            "name": payload_data.get("name"),
            "description": payload_data.get("description"),
            "is_active": payload_data.get("is_active"),
            "trigger_type": payload_data.get("trigger_type"),
            "priority": payload_data.get("priority"),
            "nodes_count": len(initial_nodes),
            "edges_count": len(initial_edges),
        },
    )
    flow_service = FlowService(db)
    flow = flow_service.create_flow(
        tenant_id=tenant_uuid,
        data={"name": payload_data.get("name")},
    )
    first_version = flow_service.create_version(flow=flow, tenant_id=tenant_uuid, nodes=initial_nodes, edges=initial_edges)
    db.commit()
    db.refresh(flow)
    return _serialize_flow_version_response(
        flow=flow,
        nodes=flow.current_version.nodes if flow.current_version else [],
        edges=flow.current_version.edges if flow.current_version else [],
        version_id=first_version.id if first_version else flow.current_version_id,
        version=flow.version,
    )


@crud_router.get("")
def list_tenant_flows(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    return [_serialize_flow(item) for item in get_flows(db=db, tenant_id=tenant_uuid)]


@crud_router.get("/{flow_id}", response_model=FlowVersionResponse)
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
        Flow.is_deleted.is_(False),
    ).first()
    logger.info("[FLOW GET DEBUG] tenant_id=%s flow_id=%s query_result=%s", str(tenant_uuid), flow_id, str(flow.id) if flow else None)

    if not flow:
        logger.error("[FLOW GET ERROR] tenant_id=%s flow_id=%s reason=flow_not_found", str(tenant_uuid), flow_id)
        raise HTTPException(status_code=404, detail="Flow não encontrado")

    resolved = FlowService(db).get_flow_with_version(flow)
    nodes = resolved["nodes"]
    edges = resolved["edges"]
    version = resolved["version"]
    logger.info("[FLOW LOAD] flow_id=%s version=%s nodes_count=%s", str(flow.id), version, len(nodes))

    return _serialize_flow_version_response(
        flow=flow,
        nodes=nodes,
        edges=edges,
        version_id=flow.current_version_id,
        version=version,
    )


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
    logger.info("[FLOW ANALYTICS] flow_id=%s tenant_id=%s analytics=%s", flow_id, tenant_uuid, analytics)
    return analytics


@crud_router.post("/{flow_id}/save", response_model=FlowVersionResponse)
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
        if not isinstance(payload_data.get("nodes"), list) or not isinstance(payload_data.get("edges"), list):
            raise HTTPException(status_code=400, detail="Payload inválido")
        logger.info("[FLOW SAVE] tenant_id=%s nodes_count=%s edges_count=%s", str(tenant_uuid), len(payload_data.get("nodes") or []), len(payload_data.get("edges") or []))
        payload_model = FlowUpdate(**payload_data)
        logger.info("FLOW RECEBIDO: %s", payload_model.model_dump())
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
        logger.info("[FLOW SAVE OK] nodes=%s edges=%s", len(nodes_json), len(edges_json))
        logger.info("VALIDANDO FLOW: nodes=%s", nodes)
        
        persisted_nodes = flow.current_version.nodes if flow.current_version and isinstance(flow.current_version.nodes, list) else []
        if len(persisted_nodes) > 2 and len(nodes) <= 1:
            raise HTTPException(
                status_code=400,
                detail="Bloqueado: tentativa de sobrescrever fluxo válido com fluxo vazio",
            )
        try:
            validate_flow_payload_or_400(nodes_json, edges_json)
        except HTTPException:
            _log_flow_version_blocked(flow.id, len(nodes))
            incoming_nodes = payload_model.nodes or []
            incoming_edges = payload_model.edges or []
            if persisted_nodes and not incoming_nodes and not incoming_edges:
                logger.error("[FLOW VERSION BLOCKED] flow_id=%s reason=empty_payload_would_overwrite_existing", str(flow.id))
            raise

        flow_service = FlowService(db)
        nova = flow_service.create_version(flow=flow, tenant_id=tenant_uuid, nodes=nodes_json, edges=edges_json)

        db.query(FlowVersion).filter(
            FlowVersion.flow_id == flow.id,
            FlowVersion.tenant_id == tenant_uuid,
            FlowVersion.id != nova.id,
        ).update(
            {"is_active": False, "is_published": False},
            synchronize_session=False,
        )

        invalidate_flow_runtime_cache(flow.id)
        if flow.is_active:
            logger.info("[FLOW ACTIVE]: %s", flow.id)
        db.commit()

        logger.info("[FLOW SAVE] tenant_id=%s flow_id=%s version_id=%s request_id=%s nodes_count=%s edges_count=%s", str(tenant_uuid), str(flow.id), str(nova.id), None, len(nodes_json), len(edges_json))
        db.refresh(flow)
        resolved = flow_service.get_flow_with_version(flow)
        return _serialize_flow_version_response(
            flow=flow,
            nodes=resolved["nodes"],
            edges=resolved["edges"],
            version_id=flow.current_version_id,
            version=flow.version,
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.exception("[FLOW SAVE ERROR] failed to save tenant flow")
        raise HTTPException(status_code=500, detail="Erro interno")


@crud_router.delete("/{flow_id}", response_model=DeleteFlowResponse)
def delete_tenant_flow(
    flow_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant_uuid)

    if not flow:
        return {"success": True, "mode": "hard_delete"}

    in_use_query = db.query(Conversation).filter(Conversation.current_flow_id == flow.id)
    if tenant_uuid is not None:
        in_use_query = in_use_query.filter(Conversation.tenant_id == tenant_uuid)
    is_in_use = db.query(in_use_query.exists()).scalar()

    if is_in_use:
        flow.is_deleted = True
        flow.deleted_at = datetime.utcnow()
        db.commit()
        return {"success": True, "mode": "soft_delete"}

    try:
        db.delete(flow)
        db.commit()
        return {"success": True, "mode": "hard_delete"}
    except Exception:
        db.rollback()
        logger.exception(
            "[FLOW DELETE FALLBACK] hard delete failed; applying soft delete",
            extra={"flow_id": str(flow.id), "tenant_id": str(tenant_uuid) if tenant_uuid else None},
        )
        flow.is_deleted = True
        flow.deleted_at = datetime.utcnow()
        db.commit()
        return {"success": True, "mode": "soft_delete"}


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
        .where(FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant_uuid)
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
            _flow_version_select(db).where(FlowVersion.id == payload.version_id, FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant_uuid)
        ).scalars().first()
    else:
        flow_version = db.execute(
            _flow_version_select(db).where(FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant_uuid).order_by(FlowVersion.version.desc()).limit(1)
        ).scalars().first()
    if not flow_version:
        raise HTTPException(status_code=404, detail="Flow version not found")

    db.query(FlowVersion).filter(FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant_uuid).update(
        {FlowVersion.is_active: False},
        synchronize_session=False,
    )
    db.query(FlowVersion).filter(FlowVersion.id == flow_version.id, FlowVersion.tenant_id == tenant_uuid).update(
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
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant = _resolve_request_tenant(db=db, tenant_id_header=x_tenant_id)
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant.id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    versions = db.execute(
        _flow_version_select(db)
        .where(FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant_uuid)
        .order_by(FlowVersion.created_at.desc(), FlowVersion.version.desc())
    ).scalars().all()
    return [_serialize_flow_version(item, flow.current_version_id) for item in versions]


@router.post("/{flow_id}/restore/{version_id}")
def restore_flow_version_by_id(
    flow_id: str,
    version_id: uuid.UUID,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant = _resolve_request_tenant(db=db, tenant_id_header=x_tenant_id)
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant.id)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    flow_version = db.execute(
        _flow_version_select(db).where(FlowVersion.id == version_id, FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant_uuid)
    ).scalars().first()
    if not flow_version:
        raise HTTPException(status_code=404, detail="Flow version not found")

    db.query(FlowVersion).filter(FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant_uuid).update(
        {FlowVersion.is_active: False},
        synchronize_session=False,
    )
    db.query(FlowVersion).filter(FlowVersion.id == flow_version.id, FlowVersion.tenant_id == tenant_uuid).update(
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


@crud_router.post("/{flow_id}/publish", response_model=FlowVersionResponse)
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
            _flow_version_select(db).where(FlowVersion.id == payload.version_id, FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant_uuid)
        ).scalars().first()
    else:
        flow_version = db.execute(
            _flow_version_select(db).where(FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant_uuid).order_by(FlowVersion.version.desc()).limit(1)
        ).scalars().first()
    if not flow_version:
        raise HTTPException(status_code=404, detail="Flow version not found")

    nodes = flow_version.nodes if isinstance(flow_version.nodes, list) else []
    edges = flow_version.edges if isinstance(flow_version.edges, list) else []
    validation = validate_flow_graph(nodes, edges, mode="publish")
    if validation["errors"]:
        raise HTTPException(status_code=422, detail=validation)

    FlowService(db).publish_version(flow=flow, flow_version=flow_version)
    flow.status = "published"
    invalidate_flow_runtime_cache(flow.id)
    db.commit()
    db.refresh(flow)
    logger.info("[FLOW PUBLISH] tenant_id=%s flow_id=%s version_id=%s request_id=%s", str(tenant_uuid), str(flow.id), str(flow_version.id), None)
    return _serialize_flow_version_response(
        flow=flow,
        nodes=nodes,
        edges=edges,
        version_id=flow.published_version_id or flow_version.id,
        version=flow.version,
    )


class FlowSimulationPayload(BaseModel):
    session_id: str | None = None
    message: str | None = None


@crud_router.post("/{flow_id}/simulate")
async def simulate_tenant_flow(
    flow_id: str,
    payload: FlowSimulationPayload,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    try:
        import traceback

        print("[SIMULATOR START REQUEST]", flow_id)
        tenant_uuid = _resolve_tenant_header(x_tenant_id)
        logger.info("[SIMULATOR START REQUEST]")
        logger.info("[SIMULATOR TENANT] %s", str(tenant_uuid))
        print("[SIMULATOR TENANT OK]")
        logger.info("[SIMULATOR FLOW_ID] %s", flow_id)
        print("[SIMULATOR FLOW_ID]", flow_id)
        print("[SIMULATOR PAYLOAD OK]", payload.model_dump())

        flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow não encontrado")

        graph = get_flow_graph(db=db, tenant_id=tenant_uuid, flow_id=str(flow.id))
        nodes = graph.get("nodes") if isinstance(graph, dict) else []
        edges = graph.get("edges") if isinstance(graph, dict) else []
        graph_source = str(graph.get("source") or "unknown") if isinstance(graph, dict) else "unknown"
        nodes = nodes if isinstance(nodes, list) else []
        edges = edges if isinstance(edges, list) else []

        has_any_version = db.execute(
            select(FlowVersion.id)
            .where(FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant_uuid)
            .limit(1)
        ).scalar_one_or_none() is not None

        if not has_any_version and not nodes:
            draft_nodes = flow.nodes_json if isinstance(flow.nodes_json, list) else flow.nodes if isinstance(flow.nodes, list) else []
            draft_edges = flow.edges_json if isinstance(flow.edges_json, list) else flow.edges if isinstance(flow.edges, list) else []
            if draft_nodes:
                nodes = draft_nodes
                edges = draft_edges if isinstance(draft_edges, list) else []
                graph_source = "flows_json_draft"
            else:
                raise HTTPException(status_code=422, detail="Salve o fluxo antes de simular")
        logger.info("[GRAPH SOURCE] %s", graph_source)
        print("[SIMULATOR GRAPH LOADED]")
        print("[SIMULATOR GRAPH SOURCE]", graph_source)
        logger.info("[GRAPH NODES COUNT] %s", len(nodes))
        print("[SIMULATOR NODES COUNT]", len(nodes))
        logger.info("[GRAPH EDGES COUNT] %s", len(edges))

        validation = validate_flow_graph(nodes, edges, mode="simulate")
        if validation["errors"]:
            raise HTTPException(status_code=422, detail=validation)

        start_node = next((n for n in nodes if isinstance(n, dict) and isinstance(n.get("data"), dict) and n.get("data", {}).get("isStart")), None)
        if not start_node and nodes:
            targets = {str(e.get("target")) for e in edges if isinstance(e, dict)}
            start_node = next((n for n in nodes if str(n.get("id")) not in targets), nodes[0])

        if not start_node:
            raise HTTPException(
                status_code=422,
                detail=f"Nenhum node encontrado na fonte {graph_source}",
            )

        session_id = (payload.session_id or "").strip() or "default"
        message = (payload.message or "").strip()
        normalized_message = message.lower()

        logger.info("[SIMULATOR SESSION_ID] %s", session_id)
        logger.info("[SIMULATOR SESSION BACKEND] db")

        def find_node(nid: str | None):
            if nid is None:
                return None
            return next((n for n in nodes if str(n.get("id")) == str(nid)), None)

        def get_next_node_id(source_node_id: str, selected_handle: str | None = None) -> str | None:
            outgoing = [e for e in edges if isinstance(e, dict) and str(e.get("source")) == str(source_node_id)]
            if not outgoing:
                return None
            if selected_handle is not None:
                selected = next(
                    (
                        e
                        for e in outgoing
                        if str(e.get("sourceHandle") or (e.get("data") or {}).get("sourceHandle") or "").lower() == selected_handle.lower()
                    ),
                    None,
                )
                if selected:
                    return str(selected.get("target"))
            return str(outgoing[0].get("target"))

        def _extract_delay_seconds(node: dict[str, Any] | None) -> int:
            data = node.get("data") if isinstance(node, dict) and isinstance(node.get("data"), dict) else {}
            raw_delay = data.get("delay") or data.get("seconds") or data.get("duration") or data.get("content") or (node.get("content") if isinstance(node, dict) else None)
            try:
                seconds = int(float(str(raw_delay).strip()))
            except Exception:
                logger.warning("[DELAY INVALID] node_id=%s raw=%s fallback=1", str((node or {}).get("id")), raw_delay)
                seconds = 1
            if seconds <= 0:
                logger.warning("[DELAY INVALID] node_id=%s raw=%s fallback=1", str((node or {}).get("id")), raw_delay)
                seconds = 1
            return seconds

        async def _resolve_operational_nodes(start_node_id: str | None) -> tuple[str, str | None, str | None]:
            cursor = start_node_id
            while cursor:
                node = find_node(cursor)
                data = node.get("data") if isinstance(node, dict) and isinstance(node.get("data"), dict) else {}
                node_type = str(data.get("type") or (node.get("type") if isinstance(node, dict) else "") or "").lower()

                if node_type == "delay":
                    logger.info("[DELAY NODE HIT] node_id=%s", cursor)
                    seconds = _extract_delay_seconds(node)
                    logger.info("[DELAY SECONDS] %s", seconds)
                    await asyncio.sleep(seconds)
                    cursor = get_next_node_id(cursor, selected_handle="default") or get_next_node_id(cursor, selected_handle="output") or get_next_node_id(cursor)
                    logger.info("[DELAY CONTINUE TO] next_node_id=%s", cursor)
                    continue

                if node_type == "action":
                    cursor = get_next_node_id(cursor, selected_handle="default") or get_next_node_id(cursor, selected_handle="output") or get_next_node_id(cursor)
                    continue

                reply_text = str(data.get("text") or data.get("content") or data.get("label") or "")
                next_id = get_next_node_id(cursor)
                logger.info("[DELAY RESPONSE NODE] node_id=%s", cursor)
                return reply_text, cursor, next_id

            return "", None, None

        simulator_user_identifier = f"simulator:{session_id}"
        sim_session = (
            db.query(FlowSession)
            .filter(
                FlowSession.tenant_id == tenant_uuid,
                FlowSession.flow_id == flow.id,
                FlowSession.user_identifier == simulator_user_identifier,
            )
            .first()
        )
        is_new_session = sim_session is None
        logger.info("[SIMULATOR SESSION NEW] %s", is_new_session)
        print("[SIMULATOR SESSION LOADED]", {"is_new": is_new_session, "session_id": session_id})

        selected_edge = None
        reply = ""
        current_node_id = None
        next_node_id = None

        if is_new_session:
            start_node_id = str(start_node.get("id"))
            current_node_id = start_node_id
            start_data = start_node.get("data") if isinstance(start_node.get("data"), dict) else {}
            reply = str(start_data.get("text") or start_data.get("content") or start_data.get("label") or "")
            next_node_id = get_next_node_id(start_node_id)

            sim_session = FlowSession(
                tenant_id=tenant_uuid,
                flow_id=flow.id,
                user_identifier=simulator_user_identifier,
                conversation_id=None,
                current_node_id=next_node_id,
                status="running" if next_node_id else "finished",
                context={"simulator": True, "session_id": session_id},
                variables={},
            )
            db.add(sim_session)
            logger.info("[SIMULATOR CURRENT NODE] %s", current_node_id)
            logger.info("[SIMULATOR NEXT NODE SAVED] %s", next_node_id)
        else:
            current_node_id = sim_session.current_node_id
            logger.info("[SIMULATOR CURRENT NODE] %s", current_node_id)

            if not current_node_id:
                reply = "Simulação finalizada. Clique em Reiniciar simulação para começar novamente."
                next_node_id = None
            else:
                current = find_node(current_node_id)
                data = current.get("data") if isinstance(current, dict) and isinstance(current.get("data"), dict) else {}
                node_type = str(data.get("type") or current.get("type") or "").lower() if isinstance(current, dict) else ""

                if "condition" in node_type:
                    logger.info("[SIMULATOR CONDITION INPUT] %s", normalized_message)
                    outgoing = [e for e in edges if isinstance(e, dict) and str(e.get("source")) == str(current_node_id)]
                    condition_match = "true" if normalized_message in {"sim", "já", "ja", "anuncio", "anúncio"} else "false"
                    logger.info("[SIMULATOR CONDITION MATCH] %s", condition_match)
                    edge = next((e for e in outgoing if str(e.get("sourceHandle") or (e.get("data") or {}).get("sourceHandle") or "").lower() == condition_match), None)
                    if edge is None and outgoing:
                        edge = outgoing[0]
                    if edge is not None:
                        selected_edge = str(edge.get("sourceHandle") or (edge.get("data") or {}).get("sourceHandle") or condition_match)
                        logger.info("[SIMULATOR EDGE SELECTED] %s", selected_edge)
                        target_id = str(edge.get("target"))
                        target_node = find_node(target_id)
                        target_data = target_node.get("data") if isinstance(target_node, dict) and isinstance(target_node.get("data"), dict) else {}
                        reply, current_node_id, next_node_id = await _resolve_operational_nodes(target_id)
                    else:
                        reply = "Condição sem saída configurada."
                        next_node_id = None
                else:
                    reply, current_node_id, next_node_id = await _resolve_operational_nodes(str(current_node_id))

                sim_session.current_node_id = next_node_id
                sim_session.status = "running" if next_node_id else "finished"
                logger.info("[SIMULATOR NEXT NODE SAVED] %s", next_node_id)

        db.commit()
        result = {
            "success": True,
            "reply": reply,
            "current_node_id": current_node_id,
            "next_node_id": next_node_id,
            "selected_edge": str(selected_edge) if selected_edge is not None else None,
        }
        logger.info("[SIMULATOR RESPONSE] %s", result)
        print("[SIMULATOR RESPONSE BUILT]", result)
        return JSONResponse(status_code=200, content=result)
    except HTTPException as e:
        logger.exception("[SIMULATOR ERROR] HTTPException flow_id=%s", flow_id)
        detail = e.detail if isinstance(e.detail, (str, dict, list)) else str(e.detail)
        return JSONResponse(
            status_code=e.status_code,
            content={"success": False, "error": "SIMULATOR_HTTP_ERROR", "detail": detail, "type": type(e).__name__},
        )
    except Exception as e:
        print("[SIMULATOR ERROR]", repr(e))
        print("[SIMULATOR TRACEBACK]", traceback.format_exc())
        logger.exception("[SIMULATOR ERROR] flow_id=%s", flow_id)
        return JSONResponse(
            status_code=500,
            content={"success": False, "error": "SIMULATOR_INTERNAL_ERROR", "detail": str(e), "type": type(e).__name__},
        )
