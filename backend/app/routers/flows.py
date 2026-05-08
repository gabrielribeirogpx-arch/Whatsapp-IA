from __future__ import annotations

import uuid
import logging
import asyncio
import hashlib
import json
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
from app.core.redis_client import get_redis_client
from app.models import Conversation, Flow, FlowSession, FlowVersion, Tenant
from app.services.flow_analytics_service import PERIODS, get_flow_analytics, resolve_analytics_period
from app.services.flow_engine_service import (
    get_flow_for_builder,
    get_flow_graph,
    invalidate_flow_runtime_cache,
    resolve_runtime_flow_graph,
    save_flow_graph,
    validate_flow as validate_flow_definition,
    validate_flow_graph,
)
from app.services.flow_runtime_service import execute_node_chain_until_reply
from app.services.flow_service import FlowService, create_flow, delete_flow, duplicate_flow, get_flow, get_flows, update_flow

router = APIRouter()
crud_router = APIRouter(tags=["flows-crud"])
logger = logging.getLogger(__name__)
logger.info("[FLOW API] carregada")

AUDIT_TEXT_MARKERS = [
    "Boa 👋 Me fala melhor",
    "Fala! 👋 Você já usa WhatsApp",
    "Ainda não consegui identificar",
]




def _graph_checksum(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str:
    payload = {"nodes": nodes if isinstance(nodes, list) else [], "edges": edges if isinstance(edges, list) else []}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()
def _extract_start_preview(nodes: list[dict[str, Any]]) -> str:
    for node in nodes:
        if not isinstance(node, dict):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        if not bool(data.get("isStart")):
            continue
        raw = data.get("text") or data.get("content") or data.get("label")
        if isinstance(raw, str):
            return " ".join(raw.strip().split())[:120]
    return ""


def _is_terminal_message_node(data: dict[str, Any]) -> bool:
    return bool(
        data.get("is_terminal")
        or data.get("isTerminal")
        or data.get("endFlow")
        or data.get("isEnd")
    )

def _publish_fresh_snapshot(db: Session, flow: Flow, *, reason: str) -> FlowVersion | None:
    nodes, edges = _builder_graph_from_flow(flow)
    if not nodes:
        logger.warning("[FLOW PUBLISH] flow_id=%s reason=%s sem nodes no builder", flow.id, reason)
        return None

    validate_flow_payload_or_400(nodes, edges)
    checksum = _graph_checksum(nodes, edges)
    start_node_id, start_text_preview = _extract_start_node_metadata(nodes)

    latest_published = (
        db.query(FlowVersion)
        .filter(FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == flow.tenant_id)
        .order_by(FlowVersion.version.desc())
        .first()
    )
    if latest_published and latest_published.graph_checksum == checksum:
        return latest_published

    db.query(FlowVersion).filter(FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == flow.tenant_id).update({FlowVersion.is_active: False, FlowVersion.is_published: False}, synchronize_session=False)
    last_version = db.execute(select(FlowVersion.version).where(FlowVersion.flow_id == flow.id).order_by(FlowVersion.version.desc()).limit(1)).scalar()
    next_version_number = (last_version or 0) + 1
    fresh_version = FlowVersion(
        flow_id=flow.id,
        tenant_id=flow.tenant_id,
        version=next_version_number,
        nodes=nodes,
        edges=edges,
        snapshot={"nodes": nodes, "edges": edges},
        graph_checksum=checksum,
        start_node_id=start_node_id,
        start_text_preview=start_text_preview,
        created_from_source="builder_graph",
        is_active=True,
        is_published=True,
    )
    db.add(fresh_version)
    db.flush()
    flow.current_version_id = fresh_version.id
    flow.published_version_id = fresh_version.id
    flow.version = fresh_version.version
    logger.info("[PUBLISH GRAPH SOURCE] flow_id=%s nodes_count=%s edges_count=%s checksum=%s start_text_preview=%s", flow.id, len(nodes), len(edges), checksum, start_text_preview)
    return fresh_version


def _ensure_published_snapshot_on_activate(db: Session, flow: Flow) -> None:
    _publish_fresh_snapshot(db=db, flow=flow, reason="activate")

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


class FlowStatusPayload(BaseModel):
    is_active: bool


class DeleteFlowResponse(BaseModel):
    success: bool = True
    mode: str = Field(
        default="hard_delete",
        description="Modo de remoção aplicado: hard_delete (remoção física) ou soft_delete (marcado como deletado).",
    )


def _extract_start_node_metadata(nodes: list[dict[str, Any]]) -> tuple[str | None, str]:
    for node in nodes:
        if not isinstance(node, dict):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        if not bool(data.get("isStart")):
            continue
        raw = data.get("text") or data.get("content") or data.get("label")
        preview = " ".join(str(raw or "").strip().split())[:120]
        return str(node.get("id")) if node.get("id") is not None else None, preview
    return None, ""


def _builder_graph_from_flow(flow: Flow) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = flow.nodes_json if isinstance(flow.nodes_json, list) else flow.nodes if isinstance(flow.nodes, list) else []
    edges = flow.edges_json if isinstance(flow.edges_json, list) else flow.edges if isinstance(flow.edges, list) else []
    if not nodes and flow.current_version and isinstance(flow.current_version.nodes, list):
        nodes = flow.current_version.nodes
    if not edges and flow.current_version and isinstance(flow.current_version.edges, list):
        edges = flow.current_version.edges
    return (nodes if isinstance(nodes, list) else []), (edges if isinstance(edges, list) else [])


def _clear_runtime_related_redis_keys(flow_id: uuid.UUID, tenant_id: uuid.UUID) -> int:
    redis = get_redis_client()
    flow_str = str(flow_id)
    tenant_str = str(tenant_id)
    cursor = 0
    deleted = 0
    while True:
        cursor, keys = redis.scan(cursor=cursor, count=300)
        for key in keys or []:
            key_text = str(key)
            lowered = key_text.lower()
            if flow_str not in key_text and tenant_str not in key_text:
                continue
            if not any(token in lowered for token in ("flow", "runtime", "session", "tenant")):
                continue
            deleted += redis.delete(key_text)
        if cursor == 0:
            break
    return deleted


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


@router.get("/tenant-flow-audit")
def tenant_flow_audit(
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flows = db.execute(select(Flow).where(Flow.tenant_id == tenant_uuid).order_by(Flow.created_at.asc(), Flow.id.asc())).scalars().all()
    sessions = db.execute(select(FlowSession).where(FlowSession.tenant_id == tenant_uuid).order_by(FlowSession.updated_at.desc()).limit(500)).scalars().all()

    payload_flows: list[dict[str, Any]] = []
    payload_sessions: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    for flow in flows:
        versions = db.execute(
            select(FlowVersion)
            .where(FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant_uuid)
            .order_by(FlowVersion.version.asc(), FlowVersion.created_at.asc())
        ).scalars().all()
        version_payload: list[dict[str, Any]] = []
        contains_texts = {marker: False for marker in AUDIT_TEXT_MARKERS}
        published_version = next((v for v in versions if v.id == flow.published_version_id), None)
        published_nodes = published_version.nodes if published_version and isinstance(published_version.nodes, list) else []
        published_node_ids = {str(n.get("id")) for n in published_nodes if isinstance(n, dict) and n.get("id") is not None}

        for version in versions:
            nodes = version.nodes if isinstance(version.nodes, list) else []
            edges = version.edges if isinstance(version.edges, list) else []
            _, start_text_preview = _extract_start_node_metadata(nodes)
            nodes_dump = json.dumps(nodes, ensure_ascii=False)
            for marker in AUDIT_TEXT_MARKERS:
                if marker in nodes_dump:
                    contains_texts[marker] = True
            start_node_id, _ = _extract_start_node_metadata(nodes)
            version_payload.append({
                "version": version.version,
                "id": str(version.id),
                "is_active": bool(version.is_active),
                "is_published": bool(version.is_published),
                "created_at": version.created_at.isoformat() if version.created_at else None,
                "nodes_count": len(nodes),
                "edges_count": len(edges),
                "start_node_id": start_node_id,
                "start_text_preview": start_text_preview,
            })

        if len([f for f in flows if f.is_active and not f.is_deleted and f.deleted_at is None]) > 1:
            findings.append({"flow_id": str(flow.id), "issue": "multiple_active_flows_for_tenant"})
        if not flow.published_version_id:
            findings.append({"flow_id": str(flow.id), "issue": "missing_published_version_id"})

        payload_flows.append({
            "id": str(flow.id),
            "name": flow.name,
            "is_active": bool(flow.is_active),
            "active": bool(flow.is_active),
            "status": flow.status,
            "deleted_at": flow.deleted_at.isoformat() if flow.deleted_at else None,
            "archived_at": getattr(flow, "archived_at", None).isoformat() if getattr(flow, "archived_at", None) else None,
            "created_at": flow.created_at.isoformat() if flow.created_at else None,
            "updated_at": flow.updated_at.isoformat() if flow.updated_at else None,
            "published_version_id": str(flow.published_version_id) if flow.published_version_id else None,
            "current_version_id": str(flow.current_version_id) if flow.current_version_id else None,
            "versions_count": len(versions),
            "contains_texts": contains_texts,
            "versions": version_payload,
        })

        for session in [s for s in sessions if s.flow_id == flow.id]:
            flow_version_id = session.variables.get("flow_version_id") if isinstance(session.variables, dict) else None
            payload_sessions.append({
                "flow_id": str(session.flow_id),
                "flow_version_id": flow_version_id,
                "current_node_id": session.current_node_id,
                "status": session.status,
                "user_identifier": session.user_identifier,
                "updated_at": session.updated_at.isoformat() if session.updated_at else None,
                "current_node_in_published_version": bool(session.current_node_id and session.current_node_id in published_node_ids),
            })

    return {
        "tenant_id": str(tenant_uuid),
        "flows": payload_flows,
        "sessions": payload_sessions,
        "findings": findings,
    }


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
            if _is_terminal_message_node(data):
                logger.info("[FLOW VALIDATION TERMINAL MESSAGE OK] node_id=%s", node_id)
                continue
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
        db.flush()
        db.refresh(flow)
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
    period: str = "7d",
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    resolved_period = resolve_analytics_period(period)
    if resolved_period != period:
        logger.info("[FLOW ANALYTICS] invalid period=%s fallback=%s allowed=%s", period, resolved_period, "|".join(PERIODS.keys()))

    analytics = get_flow_analytics(db=db, tenant_id=tenant_uuid, flow_id=flow.id, period=resolved_period)
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
    db.refresh(flow)
    _ensure_published_snapshot_on_activate(db=db, flow=flow)
    flow.is_active = True
    db.add(flow)
    invalidate_flow_runtime_cache(flow.id)
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


@crud_router.patch("/{flow_id}/status")
def update_tenant_flow_status(
    flow_id: str,
    payload: FlowStatusPayload,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow não encontrado")

    flow.is_active = payload.is_active
    db.add(flow)
    db.commit()
    db.refresh(flow)
    return _serialize_flow(flow)


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


@crud_router.get("/{flow_id}/debug-versions")
def debug_tenant_flow_versions(
    flow_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    versions = (
        db.query(FlowVersion)
        .filter(FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant_uuid)
        .order_by(FlowVersion.version.desc(), FlowVersion.created_at.desc())
        .all()
    )
    payload_versions: list[dict[str, Any]] = []
    for version in versions:
        nodes = version.nodes if isinstance(version.nodes, list) else []
        start_node_id, start_text_preview = _extract_start_node_metadata(nodes)
        payload_versions.append(
            {
                "id": str(version.id),
                "version": version.version,
                "is_active": bool(version.is_active),
                "is_published": bool(version.is_published),
                "nodes_count": len(nodes),
                "start_node_id": start_node_id,
                "start_text_preview": start_text_preview,
                "created_at": version.created_at.isoformat() if version.created_at else None,
            }
        )

    builder_graph = get_flow_for_builder(db=db, tenant_id=tenant_uuid, flow_id=str(flow.id))
    builder_nodes = builder_graph.get("nodes") if isinstance(builder_graph.get("nodes"), list) else []

    return {
        "flow_id": str(flow.id),
        "current_version_id": str(flow.current_version_id) if flow.current_version_id else None,
        "published_version_id": str(flow.published_version_id) if flow.published_version_id else None,
        "versions": payload_versions,
        "builder_graph": builder_graph,
        "builder_source": builder_graph.get("source"),
        "start_text_preview_builder": _extract_start_preview(builder_nodes),
    }


@crud_router.post("/{flow_id}/force-republish-current")
def force_republish_current_tenant_flow(
    flow_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    nodes, edges = _builder_graph_from_flow(flow)
    if not nodes:
        raise HTTPException(status_code=400, detail="Builder graph vazio: sem nodes para republicar")

    validate_flow_payload_or_400(nodes, edges)
    last_version = db.execute(
        select(FlowVersion.version).where(FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant_uuid).order_by(FlowVersion.version.desc()).limit(1)
    ).scalar()
    next_version_number = (last_version or 0) + 1

    db.query(FlowVersion).filter(FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant_uuid).update(
        {FlowVersion.is_active: False, FlowVersion.is_published: False},
        synchronize_session=False,
    )
    new_version = FlowVersion(
        flow_id=flow.id,
        tenant_id=tenant_uuid,
        version=next_version_number,
        nodes=nodes,
        edges=edges,
        snapshot={"nodes": nodes, "edges": edges},
        is_active=True,
        is_published=True,
    )
    db.add(new_version)
    db.flush()
    flow.current_version_id = new_version.id
    flow.published_version_id = new_version.id
    flow.version = new_version.version
    flow.status = "published"
    db.add(flow)
    invalidate_flow_runtime_cache(flow.id)
    db.commit()
    db.refresh(flow)

    start_node_id, start_text_preview = _extract_start_node_metadata(nodes)
    runtime_validation = validate_flow_definition({"nodes": nodes, "edges": edges}, mode="published")
    validation_errors = runtime_validation.get("errors") if isinstance(runtime_validation, dict) else []
    if not isinstance(validation_errors, list):
        validation_errors = [validation_errors]

    checksum = _graph_checksum(nodes, edges)
    response_payload = {
        "flow_id": str(flow.id),
        "version_id": str(new_version.id),
        "version": new_version.version,
        "nodes_count": len(nodes),
        "edges_count": len(edges),
        "start_node_id": start_node_id,
        "start_text_preview": start_text_preview,
        "validation_errors": validation_errors,
        "graph_checksum": checksum,
    }
    logger.info(
        "[FORCE REPUBLISH RESULT] flow_id=%s version_id=%s nodes=%s edges=%s start_node_id=%s validation_errors=%s",
        flow.id,
        new_version.id,
        len(nodes),
        len(edges),
        start_node_id,
        len(validation_errors),
    )
    if validation_errors:
        raise HTTPException(status_code=422, detail=response_payload)

    # confirmação pós-commit de que o runtime resolve sem 409
    invalidate_flow_runtime_cache(flow.id)
    try:
        resolve_runtime_flow_graph(db=db, tenant_id=tenant_uuid, flow_id=str(flow.id))
    except HTTPException as exc:
        if exc.status_code == 409:
            raise HTTPException(status_code=422, detail=exc.detail) from exc
        raise
    return {
        **response_payload,
        "new_version_id": str(new_version.id),
    }


@crud_router.post("/{flow_id}/admin-hard-reset-runtime")
def admin_hard_reset_runtime(
    flow_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    builder_graph = get_flow_for_builder(db=db, tenant_id=tenant_uuid, flow_id=str(flow.id))
    nodes = builder_graph.get("nodes") if isinstance(builder_graph, dict) else []
    edges = builder_graph.get("edges") if isinstance(builder_graph, dict) else []
    nodes = nodes if isinstance(nodes, list) else []
    edges = edges if isinstance(edges, list) else []
    if not nodes:
        raise HTTPException(status_code=400, detail="Builder graph vazio; reset cancelado sem alterações")
    validate_flow_payload_or_400(nodes, edges)

    old_versions_count = (
        db.query(FlowVersion)
        .filter(FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant_uuid)
        .count()
    )
    db.query(FlowVersion).filter(FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant_uuid).update(
        {FlowVersion.is_active: False, FlowVersion.is_published: False},
        synchronize_session=False,
    )
    flow.current_version_id = None
    flow.published_version_id = None
    db.flush()

    deleted_sessions_count = (
        db.query(FlowSession)
        .filter(FlowSession.flow_id == flow.id, FlowSession.tenant_id == tenant_uuid)
        .delete(synchronize_session=False)
    )

    cleared_cache_keys_count = _clear_runtime_related_redis_keys(flow.id, tenant_uuid)
    invalidate_flow_runtime_cache(flow.id)

    last_version = db.execute(
        select(FlowVersion.version)
        .where(FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant_uuid)
        .order_by(FlowVersion.version.desc())
        .limit(1)
    ).scalar()
    next_version_number = (last_version or 0) + 1
    new_version = FlowVersion(
        flow_id=flow.id,
        tenant_id=tenant_uuid,
        version=next_version_number,
        nodes=nodes,
        edges=edges,
        snapshot={"nodes": nodes, "edges": edges},
        is_active=True,
        is_published=True,
    )
    db.add(new_version)
    db.flush()
    flow.current_version_id = new_version.id
    flow.published_version_id = new_version.id
    flow.version = new_version.version
    flow.status = "published"
    db.add(flow)
    db.commit()

    start_node_id, start_text_preview = _extract_start_node_metadata(nodes)
    published = flow.published_version
    pub_nodes = published.nodes if published and isinstance(published.nodes, list) else []
    pub_edges = published.edges if published and isinstance(published.edges, list) else []
    pub_start_node_id, pub_start_preview = _extract_start_node_metadata(pub_nodes)
    return {
        "flow_id": str(flow.id),
        "tenant_id": str(tenant_uuid),
        "new_version_id": str(new_version.id),
        "new_version_number": new_version.version,
        "nodes_count": len(nodes),
        "edges_count": len(edges),
        "start_node_id": start_node_id,
        "start_text_preview": start_text_preview,
        "deleted_or_disabled_versions_count": old_versions_count,
        "deleted_sessions_count": deleted_sessions_count,
        "cleared_cache_keys_count": cleared_cache_keys_count,
    }


@crud_router.get("/{flow_id}/admin-runtime-audit")
@crud_router.get("/{flow_id}/runtime-audit")
def admin_runtime_audit(
    flow_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")

    versions = (
        db.query(FlowVersion)
        .filter(FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant_uuid)
        .order_by(FlowVersion.version.desc())
        .all()
    )
    old_markers = [
        "Boa 👋 Me fala melhor...",
        "Fala! 👋 Você já usa WhatsApp para vender ou atender clientes?",
    ]
    versions_payload: list[dict[str, Any]] = []
    old_text_hits: list[dict[str, Any]] = []
    for version in versions:
        nodes = version.nodes if isinstance(version.nodes, list) else []
        start_node_id, preview = _extract_start_node_metadata(nodes)
        has_old = any(marker in preview for marker in old_markers)
        if has_old:
            old_text_hits.append({"source": "flow_version", "version_id": str(version.id), "preview": preview})
        versions_payload.append(
            {
                "id": str(version.id),
                "version": version.version,
                "is_active": bool(version.is_active),
                "is_published": bool(version.is_published),
                "nodes_count": len(nodes),
                "edges_count": len(version.edges) if isinstance(version.edges, list) else 0,
                "start_node_id": start_node_id,
                "start_text_preview": preview,
            }
        )

    runtime_source = "unknown"
    try:
        runtime_graph = resolve_runtime_flow_graph(db=db, tenant_id=tenant_uuid, flow_id=str(flow.id))
        runtime_source = str(runtime_graph.get("source") or "unknown")
        runtime_preview = _extract_start_preview(runtime_graph.get("nodes") if isinstance(runtime_graph.get("nodes"), list) else [])
        if any(marker in runtime_preview for marker in old_markers):
            old_text_hits.append({"source": "runtime_graph", "preview": runtime_preview})
    except HTTPException as exc:
        runtime_graph = {"error": exc.detail}
        runtime_source = "error"

    sessions_total = db.query(FlowSession).filter(FlowSession.flow_id == flow.id, FlowSession.tenant_id == tenant_uuid).count()
    sessions_by_user_rows = (
        db.query(FlowSession.user_identifier, FlowSession.id)
        .filter(FlowSession.flow_id == flow.id, FlowSession.tenant_id == tenant_uuid)
        .all()
    )
    sessions_by_user: dict[str, int] = {}
    for user_identifier, _ in sessions_by_user_rows:
        key = str(user_identifier or "unknown")
        sessions_by_user[key] = sessions_by_user.get(key, 0) + 1

    published = flow.published_version
    pub_nodes = published.nodes if published and isinstance(published.nodes, list) else []
    pub_edges = published.edges if published and isinstance(published.edges, list) else []
    pub_start_node_id, pub_start_preview = _extract_start_node_metadata(pub_nodes)
    return {
        "flow_id": str(flow.id),
        "tenant_id": str(tenant_uuid),
        "published_version_id": str(flow.published_version_id) if flow.published_version_id else None,
        "current_version_id": str(flow.current_version_id) if flow.current_version_id else None,
        "versions": versions_payload,
        "runtime_source": runtime_source,
        "runtime_graph": runtime_graph,
        "graph_checksum": _graph_checksum(pub_nodes, pub_edges),
        "start_node_id": pub_start_node_id,
        "start_text_preview": pub_start_preview,
        "runtime_sessions_total": sessions_total,
        "runtime_sessions_by_user": sessions_by_user,
        "legacy_text_found": bool(old_text_hits),
        "legacy_text_hits": old_text_hits,
    }




@crud_router.get("/{flow_id}/publish-debug")
def publish_debug(flow_id: str, x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"), db: Session = Depends(get_db)):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    builder_nodes, builder_edges = _builder_graph_from_flow(flow)
    builder_checksum = _graph_checksum(builder_nodes, builder_edges)
    last_published = flow.published_version
    pub_nodes = last_published.nodes if last_published and isinstance(last_published.nodes, list) else []
    pub_edges = last_published.edges if last_published and isinstance(last_published.edges, list) else []
    return {
        "flow_id": str(flow.id),
        "builder_graph": {"nodes": builder_nodes, "edges": builder_edges, "checksum": builder_checksum, "start_text_preview": _extract_start_preview(builder_nodes)},
        "graph_used_in_publish": {"nodes": builder_nodes, "edges": builder_edges, "checksum": builder_checksum, "start_text_preview": _extract_start_preview(builder_nodes)},
        "last_published_graph": {"nodes": pub_nodes, "edges": pub_edges, "checksum": _graph_checksum(pub_nodes, pub_edges) if pub_nodes else None, "start_text_preview": _extract_start_preview(pub_nodes)},
        "differences": {
            "checksum_mismatch": builder_checksum != (_graph_checksum(pub_nodes, pub_edges) if pub_nodes else None),
            "start_text_preview_mismatch": _extract_start_preview(builder_nodes) != _extract_start_preview(pub_nodes),
        },
    }
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

    db.refresh(flow)
    fresh_version = _publish_fresh_snapshot(db=db, flow=flow, reason="publish")
    if not fresh_version:
        raise HTTPException(status_code=422, detail="Flow version not found")

    nodes = fresh_version.nodes if isinstance(fresh_version.nodes, list) else []
    edges = fresh_version.edges if isinstance(fresh_version.edges, list) else []
    validate_flow_payload_or_400(nodes, edges)
    validation = validate_flow_graph(nodes, edges, mode="publish")
    if "TESTE FINAL 12345" in _extract_start_preview(_builder_graph_from_flow(flow)[0]) and "TESTE FINAL 12345" not in _extract_start_preview(nodes):
        raise HTTPException(status_code=409, detail="[PUBLISH SOURCE MISMATCH]")
    if validation["errors"]:
        raise HTTPException(status_code=422, detail=validation)

    flow.status = "published"
    invalidate_flow_runtime_cache(flow.id)
    db.commit()
    db.refresh(flow)
    return _serialize_flow_version_response(
        flow=flow,
        nodes=nodes,
        edges=edges,
        version_id=flow.published_version_id or fresh_version.id,
        version=flow.version,
    )


@crud_router.post("/{flow_id}/republish", response_model=FlowVersionResponse)
def republish_tenant_flow(
    flow_id: str,
    x_tenant_id: str | None = Header(default=None, alias="X-Tenant-ID"),
    db: Session = Depends(get_db),
):
    tenant_uuid = _resolve_tenant_header(x_tenant_id)
    flow = _get_flow_by_identifier(db=db, flow_id=flow_id, tenant_id=tenant_uuid)
    if not flow:
        raise HTTPException(status_code=404, detail="Flow not found")
    fresh_version = _publish_fresh_snapshot(db=db, flow=flow, reason="republish")
    if not fresh_version:
        raise HTTPException(status_code=422, detail="Flow sem nodes para republicar")
    nodes = fresh_version.nodes if isinstance(fresh_version.nodes, list) else []
    edges = fresh_version.edges if isinstance(fresh_version.edges, list) else []
    validate_flow_payload_or_400(nodes, edges)
    validation = validate_flow_graph(nodes, edges, mode="publish")
    if "TESTE FINAL 12345" in _extract_start_preview(_builder_graph_from_flow(flow)[0]) and "TESTE FINAL 12345" not in _extract_start_preview(nodes):
        raise HTTPException(status_code=409, detail="[PUBLISH SOURCE MISMATCH]")
    if validation["errors"]:
        raise HTTPException(status_code=422, detail=validation)
    flow.status = "published"
    invalidate_flow_runtime_cache(flow.id)
    db.commit()
    db.refresh(flow)
    return _serialize_flow_version_response(flow=flow, nodes=nodes, edges=edges, version_id=fresh_version.id, version=fresh_version.version)


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

        reply = ""
        messages: list[str] = []
        current_node_id = None
        next_node_id = None

        def _extract_messages_from_runtime_result(runtime_result: dict | None) -> list[str]:
            if not isinstance(runtime_result, dict):
                return []
            events = runtime_result.get("events")
            if not isinstance(events, list):
                events = []
            logger.info("[SIMULATOR EVENTS BUILT] %s", events)
            print("[SIMULATOR EVENTS BUILT]", events)
            message_events = [
                event for event in events
                if isinstance(event, dict) and str(event.get("type") or "").strip().lower() == "send_message"
            ]
            logger.info("[SIMULATOR MESSAGE EVENTS COUNT] %s", len(message_events))
            print("[SIMULATOR MESSAGE EVENTS COUNT]", len(message_events))
            extracted = [str(event.get("text") or "").strip() for event in message_events if str(event.get("text") or "").strip()]
            if extracted:
                logger.info("[SIMULATOR REPLY TEXT] %s", "\\n\\n".join(extracted))
                print("[SIMULATOR REPLY TEXT]", "\\n\\n".join(extracted))
            return extracted

        if is_new_session:
            start_node_id = str(start_node.get("id"))
            runtime_result = await execute_node_chain_until_reply(
                graph={"nodes": nodes, "edges": edges},
                start_node_id=start_node_id,
                user_input=message,
                tenant_id=str(tenant_uuid),
                wa_id=session_id,
                db=db,
                context={"channel": "simulator"},
            )
            messages = _extract_messages_from_runtime_result(runtime_result)
            reply = "\n\n".join(messages) if messages else str(runtime_result.get("reply") or "")
            current_node_id = runtime_result.get("response_node_id") or start_node_id
            next_node_id = runtime_result.get("next_node_id")

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
                runtime_result = await execute_node_chain_until_reply(
                    graph={"nodes": nodes, "edges": edges},
                    start_node_id=str(current_node_id),
                    user_input=message,
                    tenant_id=str(tenant_uuid),
                    wa_id=session_id,
                    db=db,
                    context={"channel": "simulator"},
                )
                messages = _extract_messages_from_runtime_result(runtime_result)
                reply = "\n\n".join(messages) if messages else str(runtime_result.get("reply") or "")
                current_node_id = runtime_result.get("response_node_id") or str(current_node_id)
                next_node_id = runtime_result.get("next_node_id")
                if runtime_result.get("pending"):
                    reply = "Aguardando o tempo configurado para continuar o fluxo."
                    messages = [reply]

                sim_session.current_node_id = next_node_id
                sim_session.status = "running" if next_node_id else "finished"
                logger.info("[SIMULATOR NEXT NODE SAVED] %s", next_node_id)

        db.commit()
        result = {
            "success": True,
            "reply": reply,
            "messages": messages,
            "current_node_id": current_node_id,
            "next_node_id": next_node_id,
            "selected_edge": None,
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
