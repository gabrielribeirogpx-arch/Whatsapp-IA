from __future__ import annotations

import unicodedata
import uuid
import logging
import os
import time
import hashlib
import json
import traceback
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import desc, func, select, update
from sqlalchemy.orm import Session

from app.models import Conversation, Flow, FlowEdge, FlowNode, FlowVersion, Tenant
from app.models.flow_session import FlowSession
from app.services.delay_queue_service import enqueue_delay
from app.services.cache_service import TTL_FLOW_SECONDS, cache_aside_json
from app.services.flow_analytics_service import record_flow_event
from app.services.queue import enqueue_send_message
from app.utils.phone import normalize_phone
from app.services.flow_session_service import FlowSessionService
from app.core.redis_client import get_redis_client
from app.services.delay_queue_service import DELAY_ZSET_KEY
from app.services.whatsapp_service import send_whatsapp_document_cloud, send_whatsapp_image_cloud, send_whatsapp_list_cloud

DEFAULT_FLOW_NAME = "default_visual"
MAX_AUTO_STEPS = 10
MAX_RETRIES = 3
logger = logging.getLogger(__name__)


def _runtime_worker_id() -> str:
    return str(os.getenv("WORKER_ID") or os.getenv("HOSTNAME") or os.getpid())


def _runtime_correlation_id(context: dict[str, Any] | None = None, fallback: str | None = None) -> str:
    if isinstance(context, dict):
        for key in ("correlation_id", "message_id", "last_interactive_message_id"):
            value = str(context.get(key) or "").strip()
            if value:
                return value
    return str(fallback or "n/a")


def _log_choice_runtime_marker(
    marker: str,
    *,
    session_id: Any = None,
    current_node_id: Any = None,
    choice_node_id: Any = None,
    node_id: Any = None,
    selected_row_id: Any = None,
    selected_title: Any = None,
    target_node_id: Any = None,
    worker_id: str | None = None,
    correlation_id: str | None = None,
    reason: str | None = None,
) -> None:
    resolved_node_id = node_id or choice_node_id or current_node_id
    logger.info(
        "%s session_id=%s node_id=%s current_node_id=%s choice_node_id=%s selected_row_id=%s selected_title=%s target_node_id=%s worker_id=%s correlation_id=%s reason=%s",
        marker,
        session_id,
        resolved_node_id,
        current_node_id,
        choice_node_id,
        selected_row_id,
        selected_title,
        target_node_id,
        worker_id or _runtime_worker_id(),
        correlation_id or "n/a",
        reason or "n/a",
    )


_FLOW_RUNTIME_CACHE: dict[str, dict[str, Any]] = {}
_FLOW_RUNTIME_EVENT_GUARD: set[str] = set()
STRONG_YES_MATCHES = {"sim", "s", "claro", "quero", "com certeza", "yes"}
STRONG_NO_MATCHES = {"nao", "n", "negativo", "no"}
RUNTIME_SESSION_FINAL_STATUSES = {"completed", "finalized", "expired", "finished"}


def _raise_runtime_publish_violation(action: str) -> None:
    logger.error("[PUBLISH BLOCKED RUNTIME] action=%s", action)
    raise RuntimeError("Runtime attempted to publish flow version")


@dataclass
class VersionedFlowNode:
    id: uuid.UUID
    flow_id: uuid.UUID
    tenant_id: uuid.UUID
    type: str
    content: str | None
    metadata_json: dict[str, Any] | None
    position_x: int | None
    position_y: int | None


@dataclass
class VersionedFlowEdge:
    id: uuid.UUID
    flow_id: uuid.UUID
    source: uuid.UUID
    target: uuid.UUID
    condition: str | None
    source_handle: str | None = None




def _compute_graph_checksum(nodes: list[dict[str, Any]] | None, edges: list[dict[str, Any]] | None) -> str:
    payload = {"nodes": nodes if isinstance(nodes, list) else [], "edges": edges if isinstance(edges, list) else []}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def flow_version_nodes_edges(flow_version: FlowVersion | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if flow_version is None:
        return [], []
    nodes = flow_version.nodes_json if isinstance(getattr(flow_version, "nodes_json", None), list) else flow_version.nodes
    edges = flow_version.edges_json if isinstance(getattr(flow_version, "edges_json", None), list) else flow_version.edges
    return (nodes if isinstance(nodes, list) else []), (edges if isinstance(edges, list) else [])


def graph_hash(nodes: list[dict[str, Any]] | None, edges: list[dict[str, Any]] | None) -> str:
    return _compute_graph_checksum(nodes, edges)


def apply_flow_version_snapshot_metadata(flow_version: FlowVersion, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    nodes_payload = nodes if isinstance(nodes, list) else []
    edges_payload = edges if isinstance(edges, list) else []
    computed = graph_hash(nodes_payload, edges_payload)
    flow_version.nodes_json = nodes_payload
    flow_version.edges_json = edges_payload
    flow_version.nodes = nodes_payload
    flow_version.edges = edges_payload
    flow_version.snapshot = {"nodes": nodes_payload, "edges": edges_payload}
    flow_version.nodes_count = len(nodes_payload)
    flow_version.edges_count = len(edges_payload)
    flow_version.graph_hash = computed
    flow_version.graph_checksum = computed


def validate_flow_version_integrity(flow_version: FlowVersion) -> tuple[bool, str | None]:
    nodes, edges = flow_version_nodes_edges(flow_version)
    expected_nodes = getattr(flow_version, "nodes_count", None)
    expected_edges = getattr(flow_version, "edges_count", None)
    expected_hash = getattr(flow_version, "graph_hash", None) or getattr(flow_version, "graph_checksum", None)
    computed_hash = graph_hash(nodes, edges)
    if expected_nodes is not None and int(expected_nodes or 0) != len(nodes):
        return False, "FLOW_VERSION_NODES_COUNT_MISMATCH"
    if expected_edges is not None and int(expected_edges or 0) != len(edges):
        return False, "FLOW_VERSION_EDGES_COUNT_MISMATCH"
    if expected_hash and str(expected_hash) != computed_hash:
        return False, "FLOW_VERSION_GRAPH_HASH_MISMATCH"
    return True, None


def _runtime_cache_key(tenant_id: uuid.UUID, flow_id: uuid.UUID, version_id: uuid.UUID | None, checksum: str) -> str:
    return f"{tenant_id}:{flow_id}:{version_id}:{checksum}"
def _parse_uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    if value is None:
        return None
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _is_valid_flow_node_reference(db: Session, node_id: uuid.UUID | None) -> bool:
    if node_id is None:
        return True
    return db.execute(select(FlowNode.id).where(FlowNode.id == node_id).limit(1)).scalar_one_or_none() is not None


def _sanitize_conversation_current_node(db: Session, conversation: Conversation) -> None:
    if not _is_valid_flow_node_reference(db, conversation.current_node_id):
        logger.warning(
            "[FLOW STATE SANITIZE] clearing invalid conversation.current_node_id conversation_id=%s node_id=%s",
            conversation.id,
            conversation.current_node_id,
        )
        conversation.current_node_id = None


def _safe_set_conversation_current_node(
    db: Session,
    conversation: Conversation,
    node: FlowNode | VersionedFlowNode | uuid.UUID | None,
) -> None:
    if node is None:
        conversation.current_node_id = None
        return None
    if isinstance(node, VersionedFlowNode):
        conversation.current_node_id = None
        return None

    node_id = node.id if isinstance(node, FlowNode) else _parse_uuid(node)
    if node_id and _is_valid_flow_node_reference(db, node_id):
        conversation.current_node_id = node_id
    else:
        conversation.current_node_id = None


def validate_flow_structure(
    nodes: list[dict[str, Any]] | None,
    edges: list[dict[str, Any]] | None,
) -> tuple[bool, str | None]:
    nodes_payload = nodes if isinstance(nodes, list) else []
    edges_payload = edges if isinstance(edges, list) else []
    if not nodes_payload:
        return False, "Flow inválido: nodes vazio"

    node_ids: set[str] = set()
    start_node_id: str | None = None
    has_start = False
    for node in nodes_payload:
        if not isinstance(node, dict):
            return False, "Flow inválido: node malformado"
        node_id = str(node.get("id") or "").strip()
        if not node_id:
            return False, "Flow inválido: node sem id"
        if node_id in node_ids:
            return False, f"Flow inválido: node duplicado ({node_id})"
        node_ids.add(node_id)
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        node_type = str(
            node.get("type")
            or data.get("type")
            or data.get("nodeType")
            or "default"
        ).strip().lower()

        if node_type == "message":
            message_text = data.get("text")
            if isinstance(message_text, str):
                message_text = message_text.strip()
            if not message_text:
                return False, "Mensagem sem texto"
        elif node_type == "condition":
            condition_rule = data.get("condition")
            if isinstance(condition_rule, str):
                condition_rule = condition_rule.strip()
            if not condition_rule:
                return False, "Condição sem conteúdo"

        if bool(data.get("isStart")):
            has_start = True
            start_node_id = node_id

    if not has_start:
        return False, "Flow inválido: sem start node"

    try:
        flow = {"nodes": nodes_payload, "edges": edges_payload}
        if flow["edges"] and isinstance(flow["edges"][0], dict):
            get_source = lambda e: e.get("source")
            get_target = lambda e: e.get("target")
        else:
            get_source = lambda e: getattr(e, "source", None)
            get_target = lambda e: getattr(e, "target", None)

        outgoing_count: dict[str, int] = {node_id: 0 for node_id in node_ids}
        for edge in flow["edges"]:
            source = get_source(edge)
            target = get_target(edge)

            if not source or not target:
                raise Exception("Edge inválida: falta source ou target")

            source_exists = any(n["id"] == source for n in flow["nodes"])
            target_exists = any(n["id"] == target for n in flow["nodes"])

            if not source_exists or not target_exists:
                raise Exception("Edge inválida: node inexistente")

            outgoing_count[str(source)] = outgoing_count.get(str(source), 0) + 1
            print("[EDGE OK]:", source, "->", target)

        for node in flow["nodes"]:
            node_id = str(node.get("id") or "")
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            node_type = str(
                node.get("type")
                or data.get("type")
                or data.get("nodeType")
                or "default"
            ).strip().lower()
            is_terminal = _is_terminal_message_node(data)
            if outgoing_count.get(node_id, 0) < 1 and not (node_type == "message" and is_terminal):
                raise Exception(f"Flow inválido: node sem saída ({node_id})")
    except Exception as exc:
        return False, str(exc)

    return True, None


def _is_terminal_message_node(data: dict[str, Any]) -> bool:
    return bool(
        data.get("is_terminal")
        or data.get("isTerminal")
        or data.get("endFlow")
        or data.get("isEnd")
    )


def validate_flow_graph(nodes: list[dict[str, Any]] | None, edges: list[dict[str, Any]] | None, mode: str = "draft") -> dict[str, Any]:
    strict_mode = str(mode).lower() in {"published", "publish", "simulate"}
    nodes_payload = nodes if isinstance(nodes, list) else []
    edges_payload = edges if isinstance(edges, list) else []
    errors: list[dict[str, str | None]] = []
    warnings: list[dict[str, str | None]] = []

    def add_issue(bucket, code: str, node_id: str | None, message: str) -> None:
        bucket.append({"code": code, "node_id": node_id, "message": message})

    if not nodes_payload:
        add_issue(errors, "FLOW_EMPTY", None, "Flow vazio/inconsistente")
        return {"valid": False, "errors": errors, "warnings": warnings}

    node_map: dict[str, dict[str, Any]] = {}
    outgoing: dict[str, int] = {}
    incoming: dict[str, int] = {}
    condition_handles: dict[str, set[str]] = {}
    start_nodes: list[str] = []

    for node in nodes_payload:
        node_id = str(_node_id(node)).strip()
        if not node_id:
            add_issue(errors, "NODE_ID_REQUIRED", None, "Node sem id")
            continue
        node_map[node_id] = node  # CORREÇÃO: inserir node no map
        outgoing[node_id] = 0
        incoming[node_id] = 0
        condition_handles[node_id] = set()
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        if bool(data.get("isStart")):
            start_nodes.append(node_id)

    if len(start_nodes) != 1:
        add_issue(errors, "SINGLE_START_REQUIRED", None, "Flow precisa ter exatamente 1 start node.")

    node_ids = {str(_node_id(node)) for node in nodes_payload if str(_node_id(node)).strip()}
    node_ids_sample = list(sorted(node_ids))[:5]

    for edge in edges_payload:
        source = str(_edge_source(edge) or "").strip()
        target = str(_edge_target(edge) or "").strip()
        logger.info(
            "[FLOW VALIDATION EDGE] source=%s target=%s node_ids_sample=%s edge_raw=%s",
            source,
            target,
            node_ids_sample,
            edge,
        )
        if source not in node_ids or target not in node_ids:
            add_issue(errors, "EDGE_REFERENCE_NOT_FOUND", None, "Edge referencia node inexistente")
            continue
        outgoing[source] += 1
        incoming[target] += 1
        source_handle = str((edge.get("sourceHandle") or (edge.get("data") or {}).get("sourceHandle") or "")).lower()
        if source_handle:
            condition_handles[source].add(source_handle)

    if start_nodes:
        reachable=set(); stack=[start_nodes[0]]; adj={k:[] for k in node_map}
        for edge in edges_payload:
            src=str((edge or {}).get('source') or '').strip(); dst=str((edge or {}).get('target') or '').strip()
            if src in adj and dst in node_map: adj[src].append(dst)
        while stack:
            cur=stack.pop()
            if cur in reachable: continue
            reachable.add(cur); stack.extend(adj.get(cur,[]))
        for nid in node_map:
            if nid not in reachable:
                add_issue(errors if strict_mode else warnings, "ORPHAN_NODE", nid, "Node órfão fora do caminho do start.")

    for node_id,node in node_map.items():
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        node_type = str(node.get("type") or "").strip().lower()
        is_terminal = _is_terminal_message_node(data)

        if node_type == "message":
            text = data.get("text") if isinstance(data.get("text"), str) else data.get("content")
            if not isinstance(text, str) or not text.strip():
                add_issue(errors, "MESSAGE_TEXT_REQUIRED", node_id, "Message precisa ter texto.")
        elif node_type == "delay":
            raw_delay = data.get("delay") or data.get("seconds") or data.get("content")
            try:
                delay = float(str(raw_delay).strip())
            except Exception:
                delay = 0
            if delay <= 0:
                add_issue(errors, "DELAY_INVALID", node_id, "Delay precisa ter tempo válido > 0.")
        elif node_type == "action":
            action = data.get("action") or data.get("name")
            if not isinstance(action, str) or not action.strip():
                add_issue(errors, "ACTION_REQUIRED", node_id, "Action precisa ter nome/ação configurada.")
        elif node_type == "condition":
            handles = condition_handles.get(node_id, set())
            if not {"true", "false"}.issubset(handles):
                add_issue(errors, "CONDITION_REQUIRES_TRUE_FALSE", node_id, "Condition precisa ter saída SIM e saída NÃO.")

        if node_type == "message" and outgoing.get(node_id, 0) < 1 and is_terminal:
            logger.info("[FLOW VALIDATION TERMINAL MESSAGE OK] node_id=%s", node_id)
        elif not is_terminal and outgoing.get(node_id, 0) < 1:
            add_issue(errors if strict_mode else warnings, "NODE_WITHOUT_OUTPUT", node_id, "Este node não tem saída. Conecte a outro node ou marque como final.")

    logger.info("[FLOW VALIDATION] mode=%s valid=%s errors=%s warnings=%s", mode, len(errors)==0, len(errors), len(warnings))
    for issue in errors:
        logger.error("[FLOW VALIDATION ERROR] code=%s node_id=%s message=%s", issue.get("code"), issue.get("node_id"), issue.get("message"))
    return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}


def validate_flow(flow: dict[str, Any], mode: str = "draft") -> dict[str, Any]:
    return validate_flow_graph(flow.get("nodes"), flow.get("edges"), mode=mode)


def _is_valid_flow_payload(nodes: list[dict[str, Any]] | None, edges: list[dict[str, Any]] | None) -> bool:
    valid, _ = validate_flow_structure(nodes=nodes, edges=edges)
    return valid


def validate_flow_legacy(nodes: list[dict[str, Any]] | None, edges: list[dict[str, Any]] | None) -> tuple[bool, str | None]:
    result = validate_flow({"nodes": nodes or [], "edges": edges or []}, mode="published")
    if result["valid"]:
        return True, None
    return False, result["errors"][0] if result["errors"] else "Flow inválido"


def _get_latest_valid_flow_version(db: Session, flow_id: uuid.UUID) -> FlowVersion | None:
    versions = db.execute(
        select(FlowVersion)
        .where(FlowVersion.flow_id == flow_id)
        .order_by(FlowVersion.version.desc(), FlowVersion.created_at.desc())
    ).scalars().all()
    for version in versions:
        nodes, edges = flow_version_nodes_edges(version)
        valid, _ = validate_flow_legacy(nodes, edges)
        if valid:
            return version
    return None


def invalidate_flow_runtime_cache(flow_id: uuid.UUID) -> None:
    keys_to_remove = [k for k, v in _FLOW_RUNTIME_CACHE.items() if str(flow_id) in str(k) or (isinstance(v, dict) and str(v.get("flow_id")) == str(flow_id))]
    for key in keys_to_remove:
        _FLOW_RUNTIME_CACHE.pop(key, None)
    logger.info("[CACHE INVALIDATED] flow_id=%s keys_removed=%s", flow_id, len(keys_to_remove))


def _get_valid_flow_version_by_id(db: Session, flow: Flow, version_id: uuid.UUID | None) -> FlowVersion | None:
    if not version_id:
        return None
    selected = db.execute(
        select(FlowVersion).where(FlowVersion.id == version_id, FlowVersion.flow_id == flow.id)
    ).scalars().first()
    if not selected:
        return None
    nodes, edges = flow_version_nodes_edges(selected)
    valid, _ = validate_flow_structure(nodes=nodes, edges=edges)
    return selected if valid else None


def _get_flow_version_by_id(db: Session, flow: Flow, version_id: uuid.UUID | None) -> FlowVersion | None:
    if not version_id:
        return None
    return db.execute(
        select(FlowVersion).where(FlowVersion.id == version_id, FlowVersion.flow_id == flow.id)
    ).scalars().first()


def _serialize_persisted_flow_graph(
    db: Session,
    tenant_id: uuid.UUID,
    flow_id: uuid.UUID,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes = db.execute(
        select(FlowNode).where(FlowNode.flow_id == flow_id, FlowNode.tenant_id == tenant_id).order_by(FlowNode.created_at.asc())
    ).scalars().all()
    edges = db.execute(select(FlowEdge).where(FlowEdge.flow_id == flow_id).order_by(FlowEdge.id.asc())).scalars().all()

    return (
        [
            {
                "id": str(node.id),
                "type": node.type,
                "position": {"x": node.position_x or 0, "y": node.position_y or 0},
                "data": _extract_node_data(node),
            }
            for node in nodes
        ],
        [
            {
                "id": str(edge.id),
                "source": str(edge.source),
                "target": str(edge.target),
                "label": edge.condition,
                "data": {"condition": edge.condition},
            }
            for edge in edges
        ],
    )


def get_flow_for_builder(db: Session, tenant_id: uuid.UUID, flow_id: str) -> dict[str, Any]:
    cache_key = f"flow:{tenant_id}:{flow_id}"

    def _load_builder_flow() -> dict[str, Any]:
        flow = resolve_flow(db=db, tenant_id=tenant_id, flow_id=flow_id)
        selected_version: FlowVersion | None = None

        if flow.current_version_id:
            selected_version = db.execute(
                select(FlowVersion).where(
                    FlowVersion.id == flow.current_version_id,
                    FlowVersion.flow_id == flow.id
                )
            ).scalars().first()

        if not selected_version:
            selected_version = db.execute(
                select(FlowVersion)
                .where(FlowVersion.flow_id == flow.id)
                .order_by(FlowVersion.created_at.desc())
            ).scalars().first()

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        source_type = "empty"

        # 🔥 BLOCO CORRETO
        if selected_version:
            nodes = selected_version.nodes if isinstance(selected_version.nodes, list) else []
            raw_edges = selected_version.edges if isinstance(selected_version.edges, list) else []

            edges = []

            for edge in raw_edges:
                if not isinstance(edge, dict):
                    continue

                source_val = str(edge.get("source") or "").strip()
                target_val = str(edge.get("target") or "").strip()

                # 🔥 IGNORA EDGE INVÁLIDO (ESSA LINHA REMOVE O 400)
                if not source_val or not target_val:
                    continue

                normalized_edge = {
                    "id": str(edge.get("id") or ""),
                    "source": source_val,
                    "target": target_val,
                    "sourceHandle": edge.get("sourceHandle") or "default",
                    "targetHandle": edge.get("targetHandle") or "default",
                    "type": edge.get("type") or "default",
                    "data": edge.get("data") if isinstance(edge.get("data"), dict) else {}
                }

                edges.append(normalized_edge)

            source_type = "version"

        # 🔎 VALIDAÇÃO
        valid, error = validate_flow_structure(nodes=nodes, edges=edges)

        if source_type == "version" and not valid:
            logger.error(
                "[FLOW ERROR] load_invalid_current_version flow_id=%s version_id=%s detail=%s",
                flow.id,
                selected_version.id if selected_version else None,
                error,
            )

            fallback_version = _get_latest_valid_flow_version(db=db, flow_id=flow.id)

            if fallback_version:
                logger.warning("[FLOW RECOVERY] usando versão válida anterior")

                nodes = fallback_version.nodes if isinstance(fallback_version.nodes, list) else []
                edges = fallback_version.edges if isinstance(fallback_version.edges, list) else []
                source_type = "fallback"

        # 🧯 FALLBACK FINAL
        if not valid or not nodes:
            fallback_nodes, fallback_edges = _serialize_persisted_flow_graph(
                db=db,
                tenant_id=tenant_id,
                flow_id=flow.id
            )

            fallback_valid, _ = validate_flow_structure(
                nodes=fallback_nodes,
                edges=fallback_edges
            )

            if fallback_valid:
                nodes = fallback_nodes
                edges = fallback_edges
                source_type = "fallback"
            else:
                nodes = []
                edges = []
                source_type = "empty"

        result = {
            "flow_id": str(flow.id),
            "version_id": str(selected_version.id) if selected_version else None,
            "nodes": nodes,
            "edges": edges,
            "source": source_type,
        }

        logger.info(
            "[FLOW LOAD] flow_id=%s nodes=%s edges=%s source=%s",
            result["flow_id"],
            len(result["nodes"]),
            len(result["edges"]),
            result["source"],
        )
        return result

    cached_result = cache_aside_json(cache_key, TTL_FLOW_SECONDS, _load_builder_flow)
    return cached_result or {"flow_id": str(flow_id), "version_id": None, "nodes": [], "edges": [], "source": "empty"}




def _start_preview_from_nodes(nodes: list[dict[str, Any]] | None) -> str:
    if not isinstance(nodes, list):
        return ""
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


def _republish_from_current_nodes(db: Session, flow: Flow) -> FlowVersion | None:
    _raise_runtime_publish_violation("republish_from_current_nodes")
    current = flow.current_version
    nodes = current.nodes if current and isinstance(current.nodes, list) else []
    edges = current.edges if current and isinstance(current.edges, list) else []
    if not nodes:
        nodes = flow.nodes_json if isinstance(flow.nodes_json, list) else flow.nodes if isinstance(flow.nodes, list) else []
    if not edges:
        edges = flow.edges_json if isinstance(flow.edges_json, list) else flow.edges if isinstance(flow.edges, list) else []
    if not isinstance(nodes, list) or not nodes:
        return None
    if not isinstance(edges, list):
        edges = []
    last_version = db.query(func.max(FlowVersion.version)).filter(FlowVersion.flow_id == flow.id).scalar()
    next_version = (last_version or 0) + 1
    db.query(FlowVersion).filter(FlowVersion.flow_id == flow.id).update({FlowVersion.is_active: False, FlowVersion.is_published: False}, synchronize_session=False)
    v = FlowVersion(flow_id=flow.id, tenant_id=flow.tenant_id, version=next_version, is_active=True, is_published=True)
    apply_flow_version_snapshot_metadata(v, nodes, edges)
    db.add(v)
    db.flush()
    flow.current_version_id = v.id
    flow.published_version_id = v.id
    flow.version = v.version
    db.add(flow)
    return v
def load_published_runtime_graph(
    db: Session,
    flow_id: str,
    tenant_id: uuid.UUID,
    flow_version_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    flow = resolve_flow(db=db, tenant_id=tenant_id, flow_id=flow_id)
    selected_version_id = flow_version_id or _parse_uuid(getattr(flow, "published_version_id", None))
    if not selected_version_id:
        raise HTTPException(status_code=409, detail=f"Flow {flow.id} sem published_version_id. Publique uma versão antes de executar.")

    selected_version = _get_flow_version_by_id(db=db, flow=flow, version_id=selected_version_id)
    if not selected_version:
        raise HTTPException(status_code=409, detail=f"Published version {selected_version_id} não encontrada para flow {flow.id}.")
    integrity_ok, integrity_error = validate_flow_version_integrity(selected_version)
    if not integrity_ok:
        raise HTTPException(status_code=409, detail=f"Published version inválida: {integrity_error}")
    nodes, edges = flow_version_nodes_edges(selected_version)
    logger.info(
        "[RUNTIME GRAPH LOAD] flow_id=%s tenant_id=%s requested_flow_version_id=%s selected_flow_version_id=%s "
        "flow.published_version_id=%s flow.current_version_id=%s nodes_count=%s edges_count=%s checksum=%s",
        flow.id,
        tenant_id,
        flow_version_id,
        selected_version_id,
        getattr(flow, "published_version_id", None),
        getattr(flow, "current_version_id", None),
        len(nodes),
        len(edges),
        _compute_graph_checksum(nodes, edges) if nodes or edges else None,
    )

    if not nodes:
        logger.error("[RUNTIME GRAPH EMPTY_BLOCKED] flow_id=%s tenant_id=%s flow_version_id=%s source=%s", flow.id, tenant_id, selected_version_id, "published_version")
        raise HTTPException(status_code=409, detail=f"Published version vazia para flow {flow.id}.")

    node_ids = [str(node.get("id")) for node in nodes if isinstance(node, dict) and node.get("id") is not None]
    has_template_node = any(node_id.startswith("template-") for node_id in node_ids)
    has_template_edge = any(
        str(edge.get("source") or "").startswith("template-") or str(edge.get("target") or "").startswith("template-")
        for edge in edges
        if isinstance(edge, dict)
    )
    if has_template_node or has_template_edge:
        logger.error("[RUNTIME GRAPH TEMPLATE_ID_BLOCKED] flow_id=%s tenant_id=%s flow_version_id=%s source=%s", flow.id, tenant_id, selected_version_id, "published_version")
        raise HTTPException(status_code=409, detail=f"Published version com ids template-* para flow {flow.id}.")

    logger.info(
        "[RUNTIME GRAPH SOURCE] source=%s flow_id=%s tenant_id=%s flow_version_id=%s nodes_count=%s edges_count=%s node_ids=%s",
        "published_version",
        flow.id,
        tenant_id,
        selected_version_id,
        len(nodes),
        len(edges),
        node_ids,
    )

    graph_checksum = _compute_graph_checksum(nodes, edges)
    cache_key = _runtime_cache_key(tenant_id, flow.id, selected_version_id, graph_checksum)
    cached = _FLOW_RUNTIME_CACHE.get(cache_key)
    if cached and isinstance(cached.get("nodes"), list) and cached.get("nodes"):
        cached_node_ids = [str(node.get("id")) for node in cached.get("nodes", []) if isinstance(node, dict) and node.get("id") is not None]
        if cached_node_ids and not any(node_id.startswith("template-") for node_id in cached_node_ids):
            logger.info(
                "[RUNTIME GRAPH LOAD] flow_id=%s tenant_id=%s flow_version_id=%s source=memory_cache nodes_count=%s edges_count=%s node_ids=%s",
                flow.id,
                tenant_id,
                selected_version_id,
                len(cached.get("nodes", [])),
                len(cached.get("edges", [])) if isinstance(cached.get("edges"), list) else 0,
                cached_node_ids,
            )
            return cached

    runtime_payload = {
        "source": "published_version",
        "flow_id": str(flow.id),
        "flow_version_id": str(selected_version_id),
        "version_id": str(selected_version_id),
        "nodes": nodes,
        "edges": edges if isinstance(edges, list) else [],
        "nodes_count": len(nodes),
        "edges_count": len(edges if isinstance(edges, list) else []),
        "graph_hash": graph_checksum,
        "graph_checksum": graph_checksum,
        "cache_key": cache_key,
    }
    _FLOW_RUNTIME_CACHE[cache_key] = runtime_payload
    return runtime_payload


def resolve_runtime_flow_graph(db: Session, tenant_id: uuid.UUID, flow_id: str) -> dict[str, Any]:
    return load_published_runtime_graph(db=db, flow_id=flow_id, tenant_id=tenant_id)


def _load_flow_version_runtime(flow: Flow, tenant_id: uuid.UUID, flow_version: FlowVersion) -> dict[str, Any]:
    raw_nodes, raw_edges = flow_version_nodes_edges(flow_version)
    nodes: list[VersionedFlowNode] = []
    legacy_id_map: dict[str, uuid.UUID] = {}

    for item in raw_nodes:
        if not isinstance(item, dict):
            continue
        node_id = _parse_uuid(item.get("id")) or uuid.uuid4()
        data = item.get("data") if isinstance(item.get("data"), dict) else {}
        metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
        if data.get("text") is not None:
            metadata["text"] = data.get("text")
        if data.get("label") is not None:
            metadata["label"] = data.get("label")
        if data.get("buttons") is not None:
            metadata["buttons"] = data.get("buttons")
        if data.get("condition") is not None:
            metadata["condition"] = data.get("condition")
        if data.get("action") is not None:
            metadata["action"] = data.get("action")
        if data.get("isStart") is not None:
            metadata["isStart"] = bool(data.get("isStart"))
        position = item.get("position") if isinstance(item.get("position"), dict) else {}
        node_type = item.get("type") or "default"
        node = VersionedFlowNode(
            id=node_id,
            flow_id=flow.id,
            tenant_id=tenant_id,
            type=str(node_type),
            content=(data.get("content") or data.get("text")) if isinstance(data, dict) else None,
            metadata_json=metadata,
            position_x=int(position.get("x", 0) or 0),
            position_y=int(position.get("y", 0) or 0),
        )
        nodes.append(node)
        legacy_id_map[str(item.get("id"))] = node_id

    edges: list[VersionedFlowEdge] = []
    edges_by_source: dict[uuid.UUID, list[VersionedFlowEdge]] = {}
    for item in raw_edges:
        if not isinstance(item, dict):
            continue
        source_id = _parse_uuid(item.get("source")) or legacy_id_map.get(str(item.get("source")))
        target_id = _parse_uuid(item.get("target")) or legacy_id_map.get(str(item.get("target")))
        if not source_id or not target_id:
            continue
        edge_data = item.get("data") if isinstance(item.get("data"), dict) else {}
        condition = (
            edge_data.get("condition")
            or edge_data.get("sourceHandle")
            or item.get("label")
            or item.get("sourceHandle")
        ) or None
        edge = VersionedFlowEdge(
            id=_parse_uuid(item.get("id")) or uuid.uuid4(),
            flow_id=flow.id,
            source=source_id,
            target=target_id,
            condition=str(condition) if condition is not None else None,
            source_handle=(
                str(edge_data.get("sourceHandle") or item.get("sourceHandle"))
                if (edge_data.get("sourceHandle") or item.get("sourceHandle")) is not None
                else None
            ),
        )
        edges.append(edge)
        edges_by_source.setdefault(source_id, []).append(edge)

    node_map = build_node_map(nodes)
    logger.info(
        "[FLOW VERSION LOADED] flow_id=%s version_id=%s version=%s",
        flow.id,
        flow_version.id,
        flow_version.version,
    )
    logger.info(
        "[NODES_BY_ID KEYS] flow_id=%s version_id=%s keys=%s nodes_count=%s edges_count=%s",
        flow.id,
        flow_version.id,
        list(node_map.keys()),
        len(nodes),
        len(edges),
    )
    return {"nodes": nodes, "edges": edges, "node_map": node_map, "edges_by_source": edges_by_source}


def _empty_runtime_graph() -> dict[str, Any]:
    return {"nodes": [], "edges": [], "node_map": {}, "edges_by_source": {}}


def _get_current_flow_runtime(db: Session, flow: Flow, tenant_id: uuid.UUID, flow_version_id: uuid.UUID | None = None) -> dict[str, Any]:
    resolved = load_published_runtime_graph(db=db, flow_id=str(flow.id), tenant_id=tenant_id, flow_version_id=flow_version_id)
    if not resolved["nodes"]:
        return _empty_runtime_graph()
    runtime_version = FlowVersion(
        flow_id=flow.id,
        version=flow.version or 1,
    )
    apply_flow_version_snapshot_metadata(runtime_version, resolved["nodes"], resolved["edges"])
    if resolved.get("version_id"):
        parsed_version_id = _parse_uuid(resolved["version_id"])
        if parsed_version_id:
            runtime_version.id = parsed_version_id
    runtime = _load_flow_version_runtime(flow=flow, tenant_id=tenant_id, flow_version=runtime_version)
    nodes = runtime.get("nodes")
    edges = runtime.get("edges")
    runtime["nodes"] = nodes if isinstance(nodes, list) else []
    runtime["edges"] = edges if isinstance(edges, list) else []
    return runtime


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    # Remove pontuação e espaços extras para match robusto
    cleaned = "".join(ch for ch in without_accents if ch.isalnum() or ch.isspace())
    return " ".join(cleaned.lower().split())


def normalize_trigger_text(value: str | None) -> str:
    return _normalize_text(value or "").strip()


def is_flow_trigger(flow: Flow, incoming_text: str | None) -> bool:
    normalized_incoming = normalize_trigger_text(incoming_text)
    trigger_type = normalize_trigger_text(getattr(flow, "trigger_type", "default") or "default")
    trigger_value = normalize_trigger_text(getattr(flow, "trigger_value", None))
    default_safe_triggers = ["oi", "olá", "ola", "começar", "iniciar", "menu"]
    matched = False
    if trigger_type == "keyword":
        matched = bool(trigger_value) and normalized_incoming == trigger_value
    else:
        if trigger_value:
            matched = normalized_incoming == trigger_value
        else:
            normalized_defaults = {normalize_trigger_text(item) for item in default_safe_triggers}
            matched = normalized_incoming in normalized_defaults
            if matched:
                logger.info(
                    "[DEFAULT FLOW TRIGGER MATCHED] flow_id=%s incoming_text=%s",
                    getattr(flow, "id", None),
                    normalized_incoming,
                )
    logger.info("[FLOW TRIGGER CHECK] flow_id=%s trigger_type=%s trigger_value=%s incoming_text=%s matched=%s", getattr(flow, "id", None), trigger_type or "default", trigger_value or None, normalized_incoming, matched)
    if matched:
        logger.info("[FLOW TRIGGER MATCHED] flow_id=%s", getattr(flow, "id", None))
    else:
        logger.info("[FLOW TRIGGER NOT MATCHED] flow_id=%s", getattr(flow, "id", None))
    return matched


def _match_condition_input(normalized_input: str, keywords: list[str]) -> bool | None:
    # Prioridade 1: match literal exato da condição
    if normalized_input and normalized_input in keywords:
        return True

    # Prioridade 2: match forte sim/não (força rota sem usar fallback de intent/AI)
    if normalized_input in STRONG_YES_MATCHES:
        return True
    if normalized_input in STRONG_NO_MATCHES:
        return False

    # Prioridade 3 (fallback): heurística existente
    if not normalized_input:
        return False
    return any(
        kw
        and (
            kw in normalized_input
            or (len(normalized_input) >= 2 and normalized_input in kw)
        )
        for kw in keywords
    )


def _find_matched_keyword(normalized_input: str, keywords: list[str]) -> str | None:
    if not normalized_input:
        return None
    for kw in keywords:
        if not kw:
            continue
        if kw == normalized_input:
            return kw
    for kw in keywords:
        if not kw:
            continue
        if kw in normalized_input or (len(normalized_input) >= 2 and normalized_input in kw):
            return kw
    return None


def detect_intent(text: str) -> str | None:
    normalized_text = _normalize_text(text)
    if "api" in normalized_text or "integra" in normalized_text:
        return "api"
    if "automat" in normalized_text or "bot" in normalized_text:
        return "automacao"
    if "vender" in normalized_text or "vendas" in normalized_text:
        return "vendas"
    return None


def should_reset_context(message: str, context: dict[str, Any] | None) -> bool:
    if not isinstance(context, dict):
        return False
    normalized_message = _normalize_text(message)
    return "api" in context and "vender" in normalized_message


def _is_reset_command(normalized_message: str) -> bool:
    return normalized_message in {"menu", "iniciar", "reiniciar", "reset"}


def _is_greeting(normalized_message: str) -> bool:
    return normalized_message == "oi"


def _extract_node_data(node: FlowNode | VersionedFlowNode | dict[str, Any]) -> dict[str, Any]:
    metadata_raw = (
        _node_get(node, "metadata_json")
        or _node_get(node, "data")
        or {}
    )
    if isinstance(metadata_raw, str):
        try:
            metadata_raw = json.loads(metadata_raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            metadata_raw = {}
    metadata = metadata_raw if isinstance(metadata_raw, dict) else {}

    node_content = _node_get(node, "content")
    node_type = _node_get(node, "type")
    node_text = _node_get(node, "text") if isinstance(node, dict) else None
    node_content_dict = _node_get(node, "content") if isinstance(node, dict) else None

    return {
        "label": metadata.get("label") or node_content or node_type,
        "text": metadata.get("text") or metadata.get("message") or metadata.get("content") or node_text or node_content_dict or node_content,
        "content": node_content,
        "buttons": metadata.get("buttons") if isinstance(metadata.get("buttons"), list) else [],
        "condition": metadata.get("condition"),
        "action": metadata.get("action"),
        "isStart": bool(metadata.get("isStart", False)),
        "metadata": metadata,
    }


def _resolve_node_text(node_data: dict[str, Any]) -> str:
    metadata = node_data.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    text = (
        node_data.get("text")
        or node_data.get("content")
        or metadata.get("text")
        or ""
    )
    logger.info('[FLOW TEXT RESOLVED] text="%s"', text)
    return str(text).strip()


def tenant_has_active_visual_flow(db: Session, tenant_id: uuid.UUID) -> bool:
    return get_active_visual_flow(db=db, tenant_id=tenant_id) is not None


def get_active_visual_flow(db: Session, tenant_id: uuid.UUID) -> Flow | None:
    candidates = db.execute(
        select(Flow)
        .where(
            Flow.tenant_id == tenant_id,
            Flow.is_active.is_(True),
            Flow.is_deleted.is_(False),
            Flow.deleted_at.is_(None),
        )
        .order_by(Flow.priority.desc(), Flow.created_at.asc(), Flow.id.asc())
    ).scalars().all()
    eligible: list[Flow] = []
    for flow in candidates:
        archived_at = getattr(flow, "archived_at", None)
        if archived_at is not None:
            continue
        if not getattr(flow, "published_version_id", None):
            continue
        runtime_graph = _get_current_flow_runtime(db=db, flow=flow, tenant_id=tenant_id)
        nodes = runtime_graph.get("nodes") if isinstance(runtime_graph, dict) else None
        start_node = _find_real_start_node(nodes or []) if isinstance(nodes, list) else None
        if start_node:
            eligible.append(flow)
    if len(eligible) > 1:
        logger.error(
            "[MULTIPLE_ACTIVE_FLOWS] tenant_id=%s flow_ids=%s",
            tenant_id,
            [str(item.id) for item in eligible],
        )
        raise HTTPException(status_code=409, detail="Multiple active flows found for tenant")
    if not eligible:
        return None
    selected = eligible[0]
    logger.info(
        "[ACTIVE FLOW SELECTED] tenant_id=%s flow_id=%s flow_name=%s published_version_id=%s reason=%s",
        tenant_id,
        selected.id,
        selected.name,
        selected.published_version_id,
        "single_eligible_active_flow",
    )
    return selected


def _get_or_create_visual_flow(db: Session, tenant_id: uuid.UUID) -> Flow:
    flow = db.execute(
        select(Flow)
        .where(Flow.tenant_id == tenant_id, Flow.name == DEFAULT_FLOW_NAME)
        .order_by(Flow.created_at.asc(), Flow.id.asc())
    ).scalars().first()

    if flow:
        return flow

    flow = Flow(tenant_id=tenant_id, name=DEFAULT_FLOW_NAME)
    db.add(flow)
    db.flush()
    seed_default_visual_flow(db=db, flow=flow, tenant_id=tenant_id)
    return flow


def find_start_node(flow: Any) -> Any | None:
    nodes = getattr(flow, "nodes", None)
    if nodes is None and isinstance(flow, dict):
        nodes = flow.get("nodes", [])
    nodes = nodes or []

    return _find_real_start_node(nodes)


def _find_real_start_node(nodes: list[Any]) -> Any | None:
    def _to_dict(payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict):
            return payload
        if isinstance(payload, str):
            try:
                parsed = json.loads(payload)
                return parsed if isinstance(parsed, dict) else {}
            except (TypeError, ValueError):
                return {}
        return {}

    def _extract(node: Any) -> tuple[Any, str, str, Any, dict[str, Any], dict[str, Any]]:
        if isinstance(node, dict):
            node_id = str(node.get("id") or "")
            node_type = str(node.get("type") or "")
            top_level_is_start = node.get("isStart")
            metadata_json = _to_dict(node.get("metadata_json"))
            data = _to_dict(node.get("data"))
        else:
            node_id = str(getattr(node, "id", "") or "")
            node_type = str(getattr(node, "type", "") or "")
            top_level_is_start = getattr(node, "isStart", None)
            metadata_json = _to_dict(getattr(node, "metadata_json", None))
            data = _to_dict(getattr(node, "data", None) or getattr(node, "data_json", None))
        return node, node_id, node_type, top_level_is_start, metadata_json, data

    extracted = [_extract(node) for node in nodes]
    for _, node_id, node_type, top_level_is_start, metadata_json, data in extracted:
        logger.info("[REAL START NODE CANDIDATE] id=%s type=%s isStart=%s", node_id, node_type, data.get("isStart"))

    selected = next((item for item in extracted if item[3] is True), None)
    if not selected:
        selected = next((item for item in extracted if item[4].get("isStart") is True), None)
    if not selected:
        selected = next((item for item in extracted if item[5].get("isStart") is True), None)
    if not selected:
        selected = next((item for item in extracted if item[2].strip().lower() == "start"), None)
    if not selected:
        selected = extracted[0] if extracted else None

    if selected:
        _, node_id, node_type, _, _, data = selected
        logger.info("[REAL START NODE] id=%s type=%s isStart=%s", node_id, node_type, data.get("isStart"))
        return selected[0]
    logger.info("[REAL START NODE] id=None type=None isStart=None")
    return None




def _node_get(node: Any, key: str, default: Any = None) -> Any:
    if isinstance(node, dict):
        return node.get(key, default)
    return getattr(node, key, default)




def _node_id(node: Any) -> str:
    candidate = (
        _node_get(node, "id")
        or _node_get(node, "node_id")
    )
    return str(candidate) if candidate is not None else ""


def build_node_map(nodes: list[Any]) -> dict[str, Any]:
    return {str(_node_id(node)): node for node in nodes if _node_id(node)}
def _get_start_node(
    db: Session,
    flow_id: uuid.UUID,
    tenant_id: uuid.UUID,
    runtime_graph: dict[str, Any] | None = None,
) -> FlowNode | VersionedFlowNode | None:
    if runtime_graph:
        nodes = runtime_graph.get("nodes", [])
    else:
        raise RuntimeError("Runtime graph is required; flow_nodes is editor-only")

    check_payload = [
        {
            "id": str(_node_get(node, "id")),
            "type": _node_get(node, "type"),
            "isStart": bool((_node_get(node, "metadata_json") or _node_get(node, "data", {}) or {}).get("isStart")),
        }
        for node in nodes
    ]
    print(f"[FLOW INIT CHECK] nodes={check_payload}")
    logger.info("[FLOW INIT CHECK] nodes=%s", check_payload)

    start_node = _find_real_start_node(nodes)
    if start_node:
        start_node_id = _node_get(start_node, "id")
        print(f"[FLOW INIT FOUND] node_id={start_node_id}")
        logger.info("[FLOW INIT FOUND] node_id=%s", start_node_id)
        return start_node

    return nodes[0] if nodes else None


def _initialize_flow_start_node(
    db: Session,
    conversation: Conversation,
    flow_id: uuid.UUID,
    runtime_graph: dict[str, Any] | None = None,
    runtime_session: FlowSession | None = None,
    session_service: FlowSessionService | None = None,
) -> FlowNode | VersionedFlowNode | None:
    if runtime_graph:
        nodes = runtime_graph.get("nodes", [])
    else:
        raise RuntimeError("Runtime graph is required; flow_nodes is editor-only")

    node_payload = [
        {
            "id": _node_get(node, "id"),
            "type": _node_get(node, "type"),
            "data": _node_get(node, "metadata_json") or _node_get(node, "data", {}),
        }
        for node in nodes
    ]

    is_versioned_runtime = bool(runtime_graph and runtime_graph.get("version_id"))

    if conversation.current_node_id is None:
        start_node = _find_real_start_node(node_payload)
        if start_node:
            if is_versioned_runtime:
                _safe_set_conversation_current_node(db, conversation, None)
                if runtime_session and session_service:
                    session_service.update_session(
                        runtime_session,
                        node_id=str(start_node["id"]),
                        context=runtime_session.context if isinstance(runtime_session.context, dict) else {},
                    )
            else:
                _safe_set_conversation_current_node(db, conversation, start_node["id"])
                db.add(conversation)
                try:
                    _sanitize_conversation_current_node(db, conversation)
                    db.commit()
                    db.refresh(conversation)
                except Exception:
                    db.rollback()
                    logger.warning(
                        "[FLOW START WARNING] rollback after failing to persist conversation.current_node_id conversation_id=%s node_id=%s",
                        conversation.id,
                        start_node["id"],
                    )
                    raise
            _emit_runtime_event(
                db=db,
                tenant_id=conversation.tenant_id,
                conversation_id=conversation.id,
                flow_id=flow_id,
                flow_version_id=_parse_uuid(runtime_graph.get("version_id")) if isinstance(runtime_graph, dict) else None,
                node_id=_parse_uuid(start_node.get("id")),
                event_type="FLOW_STARTED",
                metadata={"contact_id": str(conversation.contact_id) if conversation.contact_id else None, "source": "initialize_start_node"},
                dedupe_bucket_seconds=1,
            )
            if conversation.contact_id:
                from app.services.contact_event_service import register_contact_event
                register_contact_event(
                    db,
                    tenant_id=conversation.tenant_id,
                    contact_id=conversation.contact_id,
                    event_type="flow_started",
                    title="Flow iniciado",
                    description="Entrou em automação",
                    metadata={"flow_id": str(flow_id)},
                )
            logger.info(
                "[FLOW START] node_id=%s (isStart=%s)",
                start_node["id"],
                start_node.get("data", {}).get("isStart"),
            )
            return _get_node(
                db=db,
                node_id=start_node["id"],
                tenant_id=conversation.tenant_id,
                runtime_graph=runtime_graph,
            )
        logger.error("[FLOW ERROR] Nenhum nó inicial encontrado")
        return None

    if is_versioned_runtime and runtime_session and runtime_session.current_node_id:
        parsed_runtime_node = _parse_uuid(runtime_session.current_node_id)
        if parsed_runtime_node:
            return _get_node(
                db=db,
                node_id=parsed_runtime_node,
                tenant_id=conversation.tenant_id,
                runtime_graph=runtime_graph,
            )

    if not conversation.current_node_id:
        logger.error("[FLOW ERROR] Nenhum nó inicial encontrado")
        return None

    return _get_node(
        db=db,
        node_id=conversation.current_node_id,
        tenant_id=conversation.tenant_id,
        runtime_graph=runtime_graph,
    )


def _get_node(
    db: Session,
    node_id: uuid.UUID,
    tenant_id: uuid.UUID,
    runtime_graph: dict[str, Any] | None = None,
) -> FlowNode | VersionedFlowNode | None:
    if runtime_graph:
        node_map = runtime_graph.get("node_map") if isinstance(runtime_graph.get("node_map"), dict) else {}
        return node_map.get(str(node_id))
    raise RuntimeError("Runtime graph is required; flow_nodes is editor-only")


def resolve_current_node(
    flow_data: dict[str, Any] | None,
    session: FlowSession | None,
) -> VersionedFlowNode | None:
    if not isinstance(flow_data, dict) or session is None or not session.current_node_id:
        return None
    node_id = _parse_uuid(session.current_node_id)
    if node_id is None:
        return None
    node_map = flow_data.get("node_map") if isinstance(flow_data.get("node_map"), dict) else {}
    node = node_map.get(str(node_id))
    if node:
        return node
    nodes = flow_data.get("nodes") if isinstance(flow_data.get("nodes"), list) else []
    for candidate in nodes:
        candidate_id = _parse_uuid(_node_get(candidate, "id"))
        if candidate_id == node_id:
            return candidate if isinstance(candidate, VersionedFlowNode) else None
    logger.warning(
        "[FLOW NODE RESOLUTION FAILED] current_node_id=%s available_nodes=%s flow_version=%s session_version=%s",
        session.current_node_id,
        [str(_node_get(candidate, "id")) for candidate in nodes],
        flow_data.get("version"),
        (session.variables or {}).get("flow_version") if isinstance(session.variables, dict) else None,
    )
    return None


def _get_edges(
    db: Session,
    flow_id: uuid.UUID,
    source: uuid.UUID | str | None,
    runtime_graph: dict[str, Any] | None = None,
) -> list[FlowEdge | VersionedFlowEdge]:
    if runtime_graph:
        edges_by_source = runtime_graph.get("edges_by_source", {}) if isinstance(runtime_graph.get("edges_by_source"), dict) else {}
        source_uuid = _parse_uuid(source)
        direct_edges = edges_by_source.get(source) or (edges_by_source.get(source_uuid) if source_uuid else None) or edges_by_source.get(str(source))
        if direct_edges:
            return direct_edges
        source_text = str(source_uuid or source or "")
        all_edges = runtime_graph.get("edges") if isinstance(runtime_graph.get("edges"), list) else []
        return [edge for edge in all_edges if str(_edge_source(edge)) == source_text]
    raise RuntimeError("Runtime graph is required; flow_edges is editor-only")


def _edge_source(edge: Any) -> Any:
    if isinstance(edge, dict):
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        return (
            edge.get("source")
            or edge.get("sourceNodeId")
            or edge.get("source_id")
            or edge.get("from")
            or edge.get("from_node_id")
            or data.get("source")
            or data.get("sourceNodeId")
        )
    return (
        getattr(edge, "source", None)
        or getattr(edge, "sourceNodeId", None)
        or getattr(edge, "source_id", None)
        or getattr(edge, "from_node_id", None)
        or getattr(edge, "from", None)
    )


def _edge_target(edge: Any) -> Any:
    if isinstance(edge, dict):
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        return (
            edge.get("target")
            or edge.get("targetNodeId")
            or edge.get("target_id")
            or edge.get("to")
            or edge.get("to_node_id")
            or data.get("target")
            or data.get("targetNodeId")
        )
    return (
        getattr(edge, "target", None)
        or getattr(edge, "targetNodeId", None)
        or getattr(edge, "target_id", None)
        or getattr(edge, "to_node_id", None)
        or getattr(edge, "to", None)
    )


def _edge_source_handle(edge: Any) -> Any:
    if isinstance(edge, dict):
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        return edge.get("sourceHandle") or edge.get("source_handle") or data.get("sourceHandle") or data.get("source_handle")
    data = getattr(edge, "data", None)
    data_dict = data if isinstance(data, dict) else {}
    return getattr(edge, "source_handle", None) or getattr(edge, "sourceHandle", None) or data_dict.get("sourceHandle") or data_dict.get("source_handle")


def _is_default_edge(edge: FlowEdge | VersionedFlowEdge) -> bool:
    condition = _normalize_text(getattr(edge, "condition", None))
    if condition in {"", "default", "else", "next"}:
        return True

    source_handle = _normalize_text(
        _edge_source_handle(edge)
    )
    return source_handle in {"", "default", "sourcehandle/default", "source/default"}


def _pick_default_edge(edges: list[FlowEdge | VersionedFlowEdge]) -> FlowEdge | VersionedFlowEdge | None:
    for edge in edges:
        source_handle = _normalize_text(
            _edge_source_handle(edge)
        )
        if source_handle in {"sourcehandle/default", "source/default", "default"}:
            return edge
    for edge in edges:
        if _is_default_edge(edge):
            return edge
    return edges[0] if edges else None


def _resolve_condition_routes(
    edges: list[FlowEdge | VersionedFlowEdge],
) -> tuple[FlowEdge | VersionedFlowEdge | None, FlowEdge | VersionedFlowEdge | None]:
    true_edge: FlowEdge | VersionedFlowEdge | None = None
    false_edge: FlowEdge | VersionedFlowEdge | None = None

    for edge in edges:
        edge_condition = _normalize_text(edge.condition)
        if (edge_condition in {"true", "sim", "yes"} or edge_condition.endswith("true") or edge_condition.endswith("sim")) and not true_edge:
            true_edge = edge
            continue
        if (edge_condition in {"false", "nao", "não", "no"} or edge_condition.endswith("false") or edge_condition.endswith("nao")) and not false_edge:
            false_edge = edge

    return true_edge, false_edge


def _set_flow_mode(db: Session, conversation: Conversation, flow_id: uuid.UUID, node_id: uuid.UUID) -> None:
    conversation.mode = "flow"
    conversation.current_flow = flow_id
    set_current_node(conversation=conversation, node_id=node_id, db=db)
    logger.info("[MODE SET] flow conversation_id=%s node_id=%s", conversation.id, node_id)


def _keep_flow_mode(conversation: Conversation) -> None:
    logger.info("[MODE KEEP] flow conversation_id=%s node_id=%s", conversation.id, conversation.current_node_id)
    logger.info("[FLOW MODE PRESERVED] mode=flow")
    if conversation.mode == "flow" and conversation.current_node_id:
        logger.info("[MODE PROTECTED] mantendo modo flow durante execução")


def _emit_runtime_event(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    flow_id: uuid.UUID | None,
    flow_version_id: uuid.UUID | None,
    node_id: uuid.UUID | None,
    event_type: str,
    metadata: dict[str, Any] | None = None,
    dedupe_bucket_seconds: int | None = None,
) -> None:
    if not flow_id:
        return

    if dedupe_bucket_seconds and dedupe_bucket_seconds > 0:
        bucket = int(datetime.now(timezone.utc).timestamp() // dedupe_bucket_seconds)
        guard_key = f"{conversation_id}:{node_id}:{event_type}:{bucket}"
        if guard_key in _FLOW_RUNTIME_EVENT_GUARD:
            return
        _FLOW_RUNTIME_EVENT_GUARD.add(guard_key)

    payload = dict(metadata or {})
    if flow_version_id:
        payload["flow_version_id"] = str(flow_version_id)
    try:
        record_flow_event(
            db=db,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            flow_id=flow_id,
            flow_version_id=flow_version_id,
            node_id=node_id,
            event_type=event_type,
            metadata=payload or None,
        )
    except Exception as exc:
        logger.warning(
            "[FLOW RUNTIME EVENT WARNING] event emission failed conversation_id=%s flow_id=%s flow_version_id=%s event_type=%s error=%s",
            conversation_id,
            flow_id,
            flow_version_id,
            event_type,
            exc,
        )


def emit_message_received_event(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    flow_id: uuid.UUID | None,
    flow_version_id: uuid.UUID | None,
    node_id: uuid.UUID | None,
    message_text: str,
    source: str,
    input_kind: str = "text",
    dedupe_bucket_seconds: int = 10,
) -> None:
    normalized_text = _normalize_text(message_text)
    if not normalized_text:
        return

    _emit_runtime_event(
        db=db,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        flow_id=flow_id,
        flow_version_id=flow_version_id,
        node_id=node_id,
        event_type="MESSAGE_RECEIVED",
        metadata={
            "source": source,
            "input_kind": input_kind,
            "normalized_length": len(normalized_text),
        },
        dedupe_bucket_seconds=dedupe_bucket_seconds,
    )


def _is_terminal_node(node_data: dict[str, Any], edges: list[FlowEdge | VersionedFlowEdge]) -> bool:
    return bool(
        node_data.get("is_terminal")
        or node_data.get("isTerminal")
        or node_data.get("endFlow")
        or node_data.get("isEnd")
    )


def _emit_node_entered_event(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    flow_id: uuid.UUID,
    flow_version_id: uuid.UUID | None,
    node: FlowNode | VersionedFlowNode,
    node_data: dict[str, Any],
    edges: list[FlowEdge | VersionedFlowEdge],
    step: int,
    source: str,
) -> None:
    node_type = str(node.type or "").strip().lower()
    if node_type.endswith("_node"):
        node_type = node_type[:-5]
    elif node_type.endswith("node"):
        node_type = node_type[:-4]
    _emit_runtime_event(
        db=db,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        flow_id=flow_id,
        flow_version_id=flow_version_id,
        node_id=node.id,
        event_type="NODE_ENTERED",
        metadata={
            "step": step,
            "node_type": node_type,
            "is_terminal": _is_terminal_node(node_data, edges),
            "source": source,
        },
        dedupe_bucket_seconds=10,
    )


def _is_conversion_node(node: FlowNode | VersionedFlowNode, node_data: dict[str, Any], flow: Flow) -> bool:
    node_type = str(node.type or "").strip().lower()
    if node_type.endswith("_node"):
        node_type = node_type[:-5]
    elif node_type.endswith("node"):
        node_type = node_type[:-4]

    # Regra legada (compatibilidade): apenas action node com conversion=true
    # ou node id listado em flow.settings.conversion_node_ids.
    if node_type == "action":
        if bool(node_data.get("conversion")):
            return True
        conversion_nodes = flow.settings.get("conversion_node_ids") if isinstance(flow.settings, dict) else None
        if isinstance(conversion_nodes, list):
            return str(node.id) in {str(node_id) for node_id in conversion_nodes}

    # Regra opcional no runtime resolver: tratar tipos de conversão sem depender do frontend.
    return node_type in {"conversion", "meta", "conversion_goal"}


def _ensure_conversation_state(conversation: Conversation, message_text: str) -> None:
    if not getattr(conversation, "context", None) or not isinstance(conversation.context, dict):
        conversation.context = {}

    if getattr(conversation, "retries", None) is None:
        conversation.retries = 0

    conversation.last_input = message_text or ""


def set_current_node(conversation: Conversation, node_id: uuid.UUID | None, db: Session) -> None:
    _safe_set_conversation_current_node(db, conversation, node_id)
    _sanitize_conversation_current_node(db, conversation)
    db.add(conversation)
    try:
        _sanitize_conversation_current_node(db, conversation)
        db.commit()
        db.refresh(conversation)
    except Exception:
        db.rollback()
        logger.warning(
            "[FLOW STATE WARNING] rollback after failing to persist conversation.current_node_id conversation_id=%s node_id=%s",
            conversation.id,
            node_id,
        )
        raise
    logger.info("[FLOW STATE SET] node=%s", node_id)


def _reset_to_bot_mode(db: Session, conversation: Conversation, reason: str) -> None:
    conversation.mode = "bot"
    conversation.current_flow = None
    set_current_node(conversation=conversation, node_id=None, db=db)
    _sanitize_conversation_current_node(db, conversation)
    db.commit()
    db.refresh(conversation)
    logger.info("[MODE RESET] bot conversation_id=%s reason=%s", conversation.id, reason)


def _preserve_flow_at_current_node(
    db: Session,
    conversation: Conversation,
    runtime_session: FlowSession | None = None,
    session_service: FlowSessionService | None = None,
    user_identifier: str | None = None,
    flow: Flow | None = None,
) -> None:
    if conversation.current_node_id:
        set_current_node(conversation=conversation, node_id=conversation.current_node_id, db=db)
    conversation.mode = "flow"
    _keep_flow_mode(conversation)
    if runtime_session and session_service and user_identifier and flow:
        session_service.save_runtime_session(
            tenant_id=conversation.tenant_id,
            user_identifier=user_identifier,
            flow=flow,
            current_node_id=conversation.current_node_id,
            context=conversation.context if isinstance(conversation.context, dict) else {},
            status="running",
        )


def _advance_to_edge_target(
    db: Session,
    conversation: Conversation,
    edge: FlowEdge | VersionedFlowEdge | None,
    runtime_graph: dict[str, Any] | None = None,
    runtime_session: FlowSession | None = None,
    session_service: FlowSessionService | None = None,
    flow_version_id: uuid.UUID | None = None,
    user_identifier: str | None = None,
    flow: Flow | None = None,
) -> FlowNode | VersionedFlowNode | None:
    if not edge:
        logger.info("Flow sem proxima aresta, sem nó terminal explícito; aguardando input conversation_id=%s", conversation.id)
        _preserve_flow_at_current_node(
            db=db,
            conversation=conversation,
            runtime_session=runtime_session,
            session_service=session_service,
            user_identifier=user_identifier,
            flow=flow,
        )
        return None

    if edge.target is None:
        logger.warning(
            "Flow com edge sem target conversation_id=%s edge=%s",
            conversation.id,
            edge.id,
        )
        _reset_to_bot_mode(db=db, conversation=conversation, reason="flow_error_next_node_is_none")
        return None

    next_node = _get_node(
        db=db,
        node_id=edge.target,
        tenant_id=conversation.tenant_id,
        runtime_graph=runtime_graph,
    )
    if not next_node:
        logger.warning(
            "Flow com edge sem node alvo conversation_id=%s edge=%s target_node=%s",
            conversation.id,
            edge.id,
            edge.target,
        )
        _reset_to_bot_mode(db=db, conversation=conversation, reason="flow_error_next_node_not_found")
        return None

    logger.info(
        "Flow avancando conversation_id=%s edge=%s target_node=%s",
        conversation.id,
        edge.id,
        next_node.id,
    )
    logger.info("[FLOW STATE] current=%s next=%s", conversation.current_node_id, next_node.id)
    set_current_node(conversation=conversation, node_id=next_node.id, db=db)
    logger.info("[FLOW NEXT NODE SAVED] next_node_id=%s", next_node.id)
    _keep_flow_mode(conversation)
    return next_node


def _safe_payload_json(payload: Any) -> str:
    return json.dumps(payload, default=str, ensure_ascii=False, sort_keys=True)


def _payload_summary(payload: Any, limit: int = 1200) -> str:
    encoded = _safe_payload_json(payload)
    return encoded[:limit] + ("..." if len(encoded) > limit else "")


def _choice_options_from_node(node_data: dict[str, Any], edges: list[FlowEdge | VersionedFlowEdge]) -> list[dict[str, Any]]:
    raw_buttons = node_data.get("buttons") if isinstance(node_data.get("buttons"), list) else []
    options: list[dict[str, Any]] = []
    for index, button in enumerate(raw_buttons):
        if not isinstance(button, dict):
            continue
        label = str(button.get("label") or button.get("title") or "").strip()
        if not label:
            continue
        option_value = str(button.get("value") or button.get("option_value") or button.get("handleId") or button.get("id") or label).strip()
        handle = str(button.get("handleId") or option_value or button.get("id") or _normalize_text(label).replace(" ", "_") or f"choice_{index + 1}")
        options.append({"id": handle, "label": label, "value": option_value, "handleId": handle})
    if options:
        return options
    for index, edge in enumerate(edges):
        label = str(getattr(edge, "condition", None) or _node_get(edge, "condition") or "").strip()
        if not label:
            continue
        handle = _edge_source_handle(edge) or _normalize_text(label).replace(" ", "_") or f"choice_{index + 1}"
        options.append({"id": handle, "label": label, "value": handle, "handleId": handle})
    return options



def _choice_body_text(node_data: dict[str, Any]) -> str:
    return str(node_data.get("body_text") or node_data.get("content") or "Escolha uma opção:").strip() or "Escolha uma opção:"


def _choice_sections(options: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for index, option in enumerate(options):
        label = str(option.get("label") or "").strip()
        if not label:
            continue
        rows.append({
            "id": str(option.get("id") or option.get("handleId") or f"choice_{index + 1}"),
            "title": label[:24],
            **({"description": str(option.get("description") or "")[:72]} if str(option.get("description") or "").strip() else {}),
        })
    return [{"title": "Opções", "rows": rows}] if rows else []


def _resolve_choice_option(input_text: str, options: list[dict[str, Any]]) -> dict[str, Any] | None:
    normalized_input = _normalize_text(input_text or "")
    if not normalized_input:
        return None
    for option in options:
        label = str(option.get("label") or "").strip()
        handle = str(option.get("handleId") or option.get("id") or "").strip()
        value = str(option.get("value") or "").strip()
        if _normalize_text(label) == normalized_input or _normalize_text(handle) == normalized_input or _normalize_text(value) == normalized_input:
            return option
    for option in options:
        handle = str(option.get("handleId") or option.get("id") or "")
        label = str(option.get("label") or option.get("title") or "")
        if input_text.strip() in (handle.strip(), label.strip()):
            return option
    return None


def _find_edge_for_handle(edges: list[FlowEdge | VersionedFlowEdge], handle: str | None) -> FlowEdge | VersionedFlowEdge | None:
    normalized_handle = _normalize_text(handle or "")
    if not normalized_handle:
        return None
    for edge in edges:
        edge_handle = str(_edge_source_handle(edge) or "")
        if edge_handle == handle or _normalize_text(edge_handle) == normalized_handle:
            return edge
    return None

def _choice_interactive_list_payload(body_text: str, options: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [
        {"id": str(option.get("id") or option.get("handleId") or f"choice_{index + 1}"), "title": str(option.get("label") or "")[:24]}
        for index, option in enumerate(options)
        if str(option.get("label") or "").strip()
    ]
    return {
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body_text},
            "action": {"button": "Ver opções", "sections": [{"title": "Opções", "rows": rows}]},
        },
    }


def _render_choice_prompt(node_data: dict[str, Any], edges: list[FlowEdge | VersionedFlowEdge]) -> str:
    base = (node_data.get("content") or "Escolha uma opcao:").strip()
    options = _choice_options_from_node(node_data, edges)
    button_labels = [str(option.get("label") or "").strip() for option in options if str(option.get("label") or "").strip()]

    if button_labels:
        return f"{base}\n\n" + "\n".join(f"- {label}" for label in button_labels)

    return base


def _next_flow_sequence(tenant_id: uuid.UUID, phone: str) -> int | None:
    normalized_phone = str(phone or "").strip()
    if not normalized_phone:
        return None
    try:
        redis_client = get_redis_client()
        return int(redis_client.incr(f"wa:next-seq:{tenant_id}:{normalized_phone}"))
    except Exception:
        logger.warning("[FLOW SEND SEQUENCE FALLBACK] tenant_id=%s phone=%s", tenant_id, normalized_phone, exc_info=True)
        return None




def _current_stack_trace() -> str:
    return "".join(traceback.format_stack())


def _flow_send_trace(
    *,
    engine: str,
    executor: str,
    text: Any,
    flow_id: Any = None,
    flow_version_id: Any = None,
    session_id: Any = None,
    node_id: Any = None,
    node_type: Any = None,
    message_type: str = "text",
    source: str | None = None,
) -> None:
    logger.warning(
        "[FLOW NODE SEND TRACE] engine=%s executor=%s source=%s flow_id=%s flow_version_id=%s session_id=%s node_id=%s node_type=%s message_type=%s text=%s stack=%s",
        engine,
        executor,
        source or executor,
        flow_id,
        flow_version_id,
        session_id,
        node_id,
        node_type,
        message_type,
        _text_preview(text, limit=240),
        _current_stack_trace(),
    )

def _send_flow_whatsapp_message(tenant: Tenant, phone: str, text: str, **flow_context: Any) -> str | None:
    content = (text or "").strip()
    if not content:
        print("[FLOW ERROR] texto vazio no node")
        return None

    if not phone:
        print("[FLOW ERROR] phone ausente")
        logger.warning("[FLOW SEND] Telefone ausente, mensagem nao enviada")
        return None

    print(f"[FLOW SEND] Enviando: {content}")
    logger.info("[FLOW SEND] Enfileirando mensagem: %s", content)
    _flow_send_trace(
        engine=str(flow_context.get("flow_engine") or "legacy"),
        executor=str(flow_context.get("flow_executor") or "_send_flow_whatsapp_message"),
        source=str(flow_context.get("flow_send_source") or "_send_flow_whatsapp_message"),
        text=content,
        flow_id=flow_context.get("flow_id"),
        flow_version_id=flow_context.get("flow_version_id"),
        session_id=flow_context.get("session_id"),
        node_id=flow_context.get("node_id"),
        node_type=flow_context.get("node_type"),
        message_type="text",
    )
    try:
        payload: dict[str, Any] = {"tenant_id": tenant.id, "phone": phone, "text": content}
        payload.update({
            "flow_id": str(flow_context.get("flow_id")) if flow_context.get("flow_id") else None,
            "flow_version_id": str(flow_context.get("flow_version_id")) if flow_context.get("flow_version_id") else None,
            "session_id": str(flow_context.get("session_id")) if flow_context.get("session_id") else None,
            "node_id": str(flow_context.get("node_id")) if flow_context.get("node_id") else None,
            "node_type": str(flow_context.get("node_type")) if flow_context.get("node_type") else None,
            "sequence_number": flow_context.get("sequence_number") or _next_flow_sequence(tenant.id, phone),
            "flow_engine": str(flow_context.get("flow_engine") or "legacy"),
            "flow_executor": str(flow_context.get("flow_executor") or "_send_flow_whatsapp_message"),
            "flow_send_source": str(flow_context.get("flow_send_source") or "_send_flow_whatsapp_message"),
        })
        job_id = enqueue_send_message(payload)
        print(f"[FLOW SEND RESULT] job_id={job_id}")
        return str(job_id) if job_id is not None else None
    except Exception as error:
        print(f"[FLOW ERROR] {error}")
        logger.exception("[FLOW SEND] Falha inesperada ao enviar mensagem no flow")
        return None


def enqueue_flow_send_with_tracking(
    *,
    db: Session,
    tenant_id: uuid.UUID,
    phone: str,
    text: str,
    flow_id: uuid.UUID | None = None,
    flow_version_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    node_id: uuid.UUID | None = None,
    channel: str = "whatsapp",
    buttons: list[dict[str, Any]] | None = None,
    template_or_node_text: str | None = None,
    flow_engine: str = "new",
    flow_executor: str = "enqueue_flow_send_with_tracking",
    flow_send_source: str = "enqueue_flow_send_with_tracking",
) -> str | None:
    content = (text or "").strip()
    if not content or not phone:
        return None

    has_buttons = bool(buttons)
    message_kind = "buttons" if has_buttons else "text"
    hash_source = (template_or_node_text or content).strip()
    text_hash = hashlib.sha256(hash_source.encode("utf-8")).hexdigest()[:16] if hash_source else None

    _flow_send_trace(
        engine=flow_engine,
        executor=flow_executor,
        source=flow_send_source,
        text=content,
        flow_id=flow_id,
        flow_version_id=flow_version_id,
        session_id=conversation_id,
        node_id=node_id,
        node_type="buttons" if has_buttons else "message",
        message_type=message_kind,
    )
    payload: dict[str, Any] = {"tenant_id": tenant_id, "phone": phone, "text": content, "flow_id": str(flow_id) if flow_id else None, "flow_version_id": str(flow_version_id) if flow_version_id else None, "session_id": str(conversation_id) if conversation_id else None, "node_id": str(node_id) if node_id else None, "sequence_number": _next_flow_sequence(tenant_id, phone), "flow_engine": flow_engine, "flow_executor": flow_executor, "flow_send_source": flow_send_source}
    if has_buttons:
        payload["buttons"] = buttons

    job_id = enqueue_send_message(payload)

    if flow_id and conversation_id:
        _emit_runtime_event(
            db=db,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            flow_id=flow_id,
            flow_version_id=flow_version_id,
            node_id=node_id,
            event_type="MESSAGE_SENT",
            metadata={
                "channel": channel,
                "message_kind": message_kind,
                "has_buttons": has_buttons,
                "template_or_node_text_hash": text_hash,
            },
            dedupe_bucket_seconds=1,
        )
    return job_id


def _send_flow_interactive_buttons(tenant: Tenant, phone: str, text: str, buttons: list[dict], **flow_context: Any) -> None:
    """Enfileira envio de botoes; worker aplica fallback para texto simples se falhar."""
    print(f"[FLOW BUTTON SEND] Tentando enviar botoes: {[b.get('label') for b in buttons]}")
    _flow_send_trace(
        engine=str(flow_context.get("flow_engine") or "legacy"),
        executor=str(flow_context.get("flow_executor") or "_send_flow_interactive_buttons"),
        source=str(flow_context.get("flow_send_source") or "_send_flow_interactive_buttons"),
        text=text,
        flow_id=flow_context.get("flow_id"),
        flow_version_id=flow_context.get("flow_version_id"),
        session_id=flow_context.get("session_id"),
        node_id=flow_context.get("node_id"),
        node_type=flow_context.get("node_type") or "buttons",
        message_type="interactive_buttons",
    )
    try:
        payload = {"tenant_id": tenant.id, "phone": phone, "text": text, "buttons": buttons, "flow_id": str(flow_context.get("flow_id")) if flow_context.get("flow_id") else None, "flow_version_id": str(flow_context.get("flow_version_id")) if flow_context.get("flow_version_id") else None, "session_id": str(flow_context.get("session_id")) if flow_context.get("session_id") else None, "node_id": str(flow_context.get("node_id")) if flow_context.get("node_id") else None, "node_type": str(flow_context.get("node_type") or "buttons"), "sequence_number": flow_context.get("sequence_number") or _next_flow_sequence(tenant.id, phone), "flow_engine": str(flow_context.get("flow_engine") or "legacy"), "flow_executor": str(flow_context.get("flow_executor") or "_send_flow_interactive_buttons"), "flow_send_source": str(flow_context.get("flow_send_source") or "_send_flow_interactive_buttons")}
        logger.info(
            "[CHOICE PAYLOAD GENERATED] flow_id=%s session_id=%s node_id=%s node_type=%s message_type=%s options_count=%s payload_json=%s",
            payload.get("flow_id"),
            payload.get("session_id"),
            payload.get("node_id"),
            payload.get("node_type"),
            "interactive",
            len(buttons or []),
            _safe_payload_json(payload),
        )
        job_id = enqueue_send_message(payload)
        print(f"[FLOW BUTTON SEND RESULT] job_id={job_id}")
    except Exception as error:
        print(f"[FLOW BUTTON ERROR] {error} — usando fallback texto em fila")
        _send_flow_whatsapp_message(tenant=tenant, phone=phone, text=text, **flow_context)



def _send_flow_interactive_list(tenant: Tenant, phone: str, text: str, sections: list[dict], options: list[dict], **flow_context: Any) -> str | None:
    _flow_send_trace(
        engine=str(flow_context.get("flow_engine") or "legacy"),
        executor=str(flow_context.get("flow_executor") or "_send_flow_interactive_list"),
        source=str(flow_context.get("flow_send_source") or "_send_flow_interactive_list"),
        text=text,
        flow_id=flow_context.get("flow_id"),
        flow_version_id=flow_context.get("flow_version_id"),
        session_id=flow_context.get("session_id"),
        node_id=flow_context.get("node_id"),
        node_type=flow_context.get("node_type") or "choice",
        message_type="interactive_list",
    )
    try:
        payload = {
            "tenant_id": tenant.id,
            "phone": phone,
            "text": text,
            "interactive_type": "list",
            "sections": sections,
            "options": options,
            "flow_id": str(flow_context.get("flow_id")) if flow_context.get("flow_id") else None,
            "flow_version_id": str(flow_context.get("flow_version_id")) if flow_context.get("flow_version_id") else None,
            "session_id": str(flow_context.get("session_id")) if flow_context.get("session_id") else None,
            "node_id": str(flow_context.get("node_id")) if flow_context.get("node_id") else None,
            "node_type": str(flow_context.get("node_type") or "choice"),
            "sequence_number": flow_context.get("sequence_number") or _next_flow_sequence(tenant.id, phone),
            "flow_engine": str(flow_context.get("flow_engine") or "legacy"),
            "flow_executor": str(flow_context.get("flow_executor") or "_send_flow_interactive_list"),
            "flow_send_source": str(flow_context.get("flow_send_source") or "_send_flow_interactive_list"),
        }
        logger.info(
            "[CHOICE LIST ENQUEUED] flow_id=%s session_id=%s node_id=%s node_type=%s message_type=%s interactive_type=%s options_count=%s payload_summary=%s",
            payload.get("flow_id"),
            payload.get("session_id"),
            payload.get("node_id"),
            payload.get("node_type"),
            "interactive",
            "list",
            len(options or []),
            _payload_summary(payload),
        )
        return enqueue_send_message(payload)
    except Exception:
        logger.exception("[CHOICE LIST ENQUEUE ERROR] flow_id=%s node_id=%s", flow_context.get("flow_id"), flow_context.get("node_id"))
        return _send_flow_whatsapp_message(tenant=tenant, phone=phone, text=text, **flow_context)

def _text_preview(value: str | None, limit: int = 120) -> str:
    if not value:
        return ""
    text = " ".join(str(value).split())
    return text[:limit]






def _node_type_slug(node: FlowNode | VersionedFlowNode | None) -> str:
    node_type = str(_node_get(node, "type") or "").strip().lower() if node else ""
    if node_type.endswith("_node"):
        node_type = node_type[:-5]
    elif node_type.endswith("node"):
        node_type = node_type[:-4]
    return node_type


def _assert_not_persisting_message_node_with_outgoing_edge(
    *,
    db: Session,
    tenant_id: uuid.UUID,
    flow_id: uuid.UUID,
    node_id: uuid.UUID | None,
    runtime_graph: dict[str, Any] | None,
) -> None:
    if node_id is None:
        return
    node = _get_node(db=db, node_id=node_id, tenant_id=tenant_id, runtime_graph=runtime_graph)
    if _node_type_slug(node) != "message":
        return
    out_edges = _get_edges(db=db, flow_id=flow_id, source=node_id, runtime_graph=runtime_graph)
    if out_edges:
        raise RuntimeError("Attempted to save message node with outgoing edge as current_node_id")


def _is_wait_node_type(node_type: str) -> bool:
    return node_type in {"condition", "input", "question", "wait_user_response", "choice", "buttons", "list", "buttons_node", "list_node"}






def _log_session_node_transition(
    phase: str,
    *,
    flow_session: FlowSession | None,
    conversation: Conversation | None = None,
    executed_node_id: Any = None,
    next_node_id: Any = None,
    current_node_id: Any = None,
    reason: str | None = None,
) -> None:
    context = getattr(conversation, "context", None)
    flow_current_node_id = context.get("flow_current_node_id") if isinstance(context, dict) else None
    logger.info(
        "[SESSION NODE %s] session_id=%s current_node_id=%s flow_current_node_id=%s "
        "node_id_executado=%s next_node_id=%s status=%s reason=%s",
        phase,
        getattr(flow_session, "id", None),
        current_node_id if current_node_id is not None else getattr(flow_session, "current_node_id", None),
        flow_current_node_id,
        executed_node_id,
        next_node_id,
        getattr(flow_session, "status", None),
        reason or "",
    )

def _finalize_runtime_flow_session(db: Session, conversation: Conversation, flow_session: FlowSession | None, end_node_id: Any) -> None:
    logger.info(
        "[SESSION FINALIZE CALL] session_id=%s flow_id=%s current_node_id=%s end_node_id=%s",
        getattr(flow_session, "id", None),
        getattr(flow_session, "flow_id", None),
        getattr(flow_session, "current_node_id", None),
        end_node_id,
    )
    logger.info(
        "[SESSION FINALIZE REASON] reason=flow_finished status_before=%s conversation_id=%s",
        getattr(flow_session, "status", None),
        getattr(conversation, "id", None),
    )
    logger.info("[SESSION FINALIZE STACK] %s", " | ".join(traceback.format_stack(limit=12)))
    _log_session_node_transition(
        "BEFORE",
        flow_session=flow_session,
        conversation=conversation,
        executed_node_id=end_node_id,
        next_node_id=None,
        reason="finalize_runtime_flow_session",
    )
    if flow_session:
        end_node_uuid = _parse_uuid(end_node_id)
        _emit_runtime_event(
            db=db,
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            flow_id=getattr(flow_session, "flow_id", None),
            flow_version_id=getattr(flow_session, "flow_version_id", None),
            node_id=end_node_uuid,
            event_type="FLOW_COMPLETED",
            metadata={"flow_session_id": str(flow_session.id), "contact_id": str(conversation.contact_id) if conversation.contact_id else None},
            dedupe_bucket_seconds=1,
        )
        if conversation.contact_id:
            from app.services.contact_event_service import register_contact_event
            register_contact_event(
                db,
                tenant_id=conversation.tenant_id,
                contact_id=conversation.contact_id,
                event_type="flow_completed",
                title="Flow concluído",
                description="Concluiu automação",
                metadata={"flow_session_id": str(flow_session.id)},
            )
        session_service = FlowSessionService(db)
        flow_session.status = "completed"
        flow_session.current_node_id = session_service.safe_update_current_node(
            session=flow_session,
            next_node_id=None,
            reason="flow_finished",
            graph_context={
                "end_node_id": str(end_node_id) if end_node_id else None,
                "executed_node_id": str(end_node_id) if end_node_id else None,
            },
        )
        if hasattr(flow_session, "completed_at"):
            setattr(flow_session, "completed_at", datetime.utcnow())
        if isinstance(flow_session.context, dict):
            flow_session.context.pop("pending_input", None)
            flow_session.context.pop("last_condition", None)
            flow_session.context.pop("condition", None)
        if isinstance(flow_session.variables, dict):
            flow_session.variables.pop("pending_input", None)
            flow_session.variables.pop("last_condition", None)
            flow_session.variables.pop("condition", None)
            flow_session.variables.pop("current_node_id", None)
        db.add(flow_session)

    if isinstance(conversation.context, dict):
        conversation.context.pop("pending_input", None)
        conversation.context.pop("last_condition", None)
        conversation.context.pop("condition", None)
        conversation.context["flow_current_node_id"] = None

    conversation.current_node_id = None
    _log_session_node_transition(
        "AFTER",
        flow_session=flow_session,
        conversation=conversation,
        executed_node_id=end_node_id,
        next_node_id=None,
        reason="finalize_runtime_flow_session",
    )
    db.add(conversation)
    db.commit()
    _log_session_node_transition(
        "PERSIST",
        flow_session=flow_session,
        conversation=conversation,
        executed_node_id=end_node_id,
        next_node_id=None,
        reason="finalize_runtime_flow_session",
    )
    if flow_session:
        redis_client = get_redis_client()
        for entry in redis_client.zrange(DELAY_ZSET_KEY, 0, -1):
            try:
                raw_entry = entry.decode("utf-8") if isinstance(entry, bytes) else str(entry)
                payload = json.loads(raw_entry)
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if str(payload.get("flow_session_id") or "") != str(flow_session.id):
                continue
            redis_client.zrem(DELAY_ZSET_KEY, entry)
            logger.info("[DELAY INVALIDATED] flow_session_id=%s payload_next_node_id=%s", flow_session.id, payload.get("next_node_id"))
    logger.info("[FLOW FINISHED] session_id=%s end_node_id=%s", getattr(flow_session, "id", None), end_node_id)
def run_until_wait_node(
    db: Session,
    flow: Flow,
    runtime_graph: dict[str, Any],
    session: Conversation,
    start_node_id: uuid.UUID | None,
    incoming_text: str | None = None,
) -> FlowNode | VersionedFlowNode | None:
    logger.info("[MANYCHAT ENGINE START] start_node_id=%s", start_node_id)
    session_service = FlowSessionService(db)
    flow_session, _ = session_service.get_runtime_session(session.tenant_id, session.phone_number, flow)
    node = _get_node(db=db, node_id=start_node_id, tenant_id=session.tenant_id, runtime_graph=runtime_graph) if start_node_id else None
    normalized_input = _normalize_text(incoming_text or "")
    choice_target_trace: dict[str, Any] | None = None
    if node:
        node_data = _extract_node_data(node)
        is_start_node = bool(node_data.get("isStart"))
        logger.info(
            "[MANYCHAT ACTUAL FIRST NODE] node_id=%s node_type=%s is_start=%s",
            _node_get(node, "id"),
            _node_type_slug(node),
            is_start_node,
        )
        if normalized_input and is_start_node:
            logger.warning("[MANYCHAT INVALID_RESTART_BLOCKED] reason=incoming_text_started_at_start_node")
            runtime_current_node_id = _parse_uuid(getattr(session, "current_node_id", None))
            if runtime_current_node_id is not None and runtime_current_node_id != _parse_uuid(start_node_id):
                logger.info(
                    "[MANYCHAT RESTART BLOCKED_CONTINUING_FROM_SESSION] current_node_id=%s incoming_text=%s",
                    runtime_current_node_id,
                    incoming_text,
                )
                return run_until_wait_node(
                    db=db,
                    flow=flow,
                    runtime_graph=runtime_graph,
                    session=session,
                    start_node_id=runtime_current_node_id,
                    incoming_text=incoming_text,
                )
            logger.warning("[FLOW CONTINUATION LOST_STATE] session_id=%s incoming_text_present=true", getattr(session, "id", None))
            return None
    steps = 0
    visited_node_ids: set[uuid.UUID] = set()
    while node and steps < MAX_AUTO_STEPS:
        steps += 1
        current_node_id = _parse_uuid(_node_get(node, "id"))
        if current_node_id is not None and current_node_id in visited_node_ids:
            logger.warning("[MANYCHAT LOOP DETECTED] node_id=%s", current_node_id)
            return None
        if current_node_id is not None:
            visited_node_ids.add(current_node_id)
        node_type = _node_type_slug(node)
        node_data = _extract_node_data(node)
        edges = _get_edges(db=db, flow_id=flow.id, source=_node_get(node, "id"), runtime_graph=runtime_graph)
        current_node_uuid = _parse_uuid(_node_get(node, "id"))
        _emit_node_entered_event(
            db=db,
            tenant_id=session.tenant_id,
            conversation_id=session.id,
            flow_id=flow.id,
            flow_version_id=getattr(flow_session, "flow_version_id", None),
            node=node,
            node_data=node_data,
            edges=edges,
            step=steps,
            source="runtime_loop",
        )
        logger.info("[MANYCHAT NODE EXECUTE] node_id=%s node_type=%s", _node_get(node, "id"), node_type)
        logger.info(
            "[NODE EXECUTE] flow_id=%s session_id=%s current_node_id=%s next_node_id=%s node_type=%s",
            flow.id,
            getattr(flow_session, "id", None),
            _node_get(node, "id"),
            None,
            node_type,
        )

        if node_type == "choice":
            logger.info(
                "[CHOICE NODE ENTER] session_id=%s node_id=%s flow_id=%s interactive_type=%s payload_summary=%s",
                getattr(flow_session, "id", None),
                _node_get(node, "id"),
                flow.id,
                "list",
                _payload_summary({"node_type": node_type, "node_data_keys": sorted(node_data.keys()), "edges_count": len(edges)}),
            )
            choice_options = _choice_options_from_node(node_data, edges)
            choice_body_text = _choice_body_text(node_data)
            choice_sections = _choice_sections(choice_options)
            choice_context = flow_session.context if flow_session and isinstance(flow_session.context, dict) else {}
            input_selected_row_id = str(choice_context.get("selected_row_id") or choice_context.get("last_interactive_list_reply_id") or "").strip()
            input_selected_title = str(choice_context.get("selected_title") or choice_context.get("last_interactive_list_reply_title") or "").strip()
            input_waiting_choice = choice_context.get("waiting_choice")
            input_choice_node_id = choice_context.get("choice_node_id")
            logger.info(
                "[CHOICE INPUT] incoming_text=%s selected_row_id=%s selected_title=%s waiting_choice=%s choice_node_id=%s",
                incoming_text,
                input_selected_row_id,
                input_selected_title,
                input_waiting_choice,
                input_choice_node_id,
            )
            flow_context = flow_session.context if flow_session and isinstance(flow_session.context, dict) else {}
            effective_input = (
                flow_context.get("selected_row_id")
                or flow_context.get("last_interactive_list_reply_id")
                or incoming_text
                or ""
            )
            selected_option = _resolve_choice_option(effective_input, choice_options)
            if not selected_option and incoming_text and effective_input != incoming_text:
                selected_option = _resolve_choice_option(incoming_text, choice_options)
            logger.info(
                "[CHOICE RESOLVE RESULT] selected_option=%s selected_handle=%s selected_label=%s",
                _payload_summary(selected_option),
                selected_option.get("handleId") or selected_option.get("id") if selected_option else None,
                selected_option.get("label") if selected_option else None,
            )
            logger.info(
                "[CHOICE LIST GENERATED] flow_id=%s session_id=%s node_id=%s node_type=%s message_type=%s interactive_type=%s options_count=%s payload_summary=%s",
                flow.id,
                getattr(flow_session, "id", None),
                _node_get(node, "id"),
                node_type,
                "interactive",
                "list",
                len(choice_options),
                _payload_summary({"body_text": choice_body_text, "sections": choice_sections, "options": choice_options}),
            )
            if selected_option is None and choice_context.get("waiting_choice"):
                logger.warning(
                    "[CHOICE RESUME NO_SELECTION_RESEND] "
                    "session_id=%s node_id=%s resending interactive list",
                    getattr(flow_session, "id", None),
                    _node_get(node, "id"),
                )
            if selected_option:
                selected_handle = str(selected_option.get("handleId") or selected_option.get("id") or "")
                selected_title = str(selected_option.get("label") or "")
                option_value = selected_handle
                available_edges = [
                    {"source_handle": _edge_source_handle(edge), "target_node": _edge_target(edge)}
                    for edge in edges
                ]
                logger.info(
                    "[CHOICE EDGE LOOKUP] source_handle=%s available_edges=%s",
                    selected_handle,
                    _payload_summary(available_edges),
                )
                selected_edge = _find_edge_for_handle(edges, selected_handle)
                next_node_id = _edge_target(selected_edge) if selected_edge else None
                if selected_edge:
                    logger.info("[CHOICE EDGE FOUND] target_node=%s", next_node_id)
                flow_context = flow_session.context if flow_session and isinstance(flow_session.context, dict) else {}
                correlation_id = _runtime_correlation_id(flow_context)
                _log_choice_runtime_marker(
                    "[CHOICE LIST RESPONSE]",
                    session_id=getattr(flow_session, "id", None),
                    current_node_id=_node_get(node, "id"),
                    choice_node_id=_node_get(node, "id"),
                    selected_row_id=selected_handle,
                    target_node_id=next_node_id,
                    correlation_id=correlation_id,
                )
                _log_choice_runtime_marker(
                    "[CHOICE OPTION RESOLVED]",
                    session_id=getattr(flow_session, "id", None),
                    current_node_id=_node_get(node, "id"),
                    choice_node_id=_node_get(node, "id"),
                    selected_row_id=selected_handle,
                    target_node_id=next_node_id,
                    correlation_id=correlation_id,
                )
                logger.info(
                    "[CHOICE LIST RESPONSE DETAIL] flow_id=%s session_id=%s node_id=%s selected_row_id=%s selected_title=%s incoming_text=%s",
                    flow.id, getattr(flow_session, "id", None), _node_get(node, "id"), selected_handle, selected_title, incoming_text,
                )
                if flow_session:
                    flow_session.context = {
                        **(flow_session.context or {}),
                        "waiting_choice": False,
                        "last_interactive_list_reply_id": selected_handle,
                        "last_interactive_list_reply_title": selected_title,
                        "selected_row_id": selected_handle,
                        "selected_title": selected_title,
                        "selected_choice_option_value": option_value,
                        "selected_choice_raw_value": str(selected_option.get("value") or ""),
                        "selected_choice_target_node_id": str(next_node_id) if next_node_id else None,
                    }
                    db.add(flow_session)
                _emit_runtime_event(
                    db=db, tenant_id=session.tenant_id, conversation_id=session.id, flow_id=flow.id,
                    flow_version_id=getattr(flow_session, "flow_version_id", None), node_id=current_node_uuid,
                    event_type="LIST_SELECTED", metadata={"option_id": selected_handle, "label": selected_title, "source": "choice"}, dedupe_bucket_seconds=1,
                )
                node = _get_node(db=db, node_id=next_node_id, tenant_id=session.tenant_id, runtime_graph=runtime_graph) if selected_edge else None
                target_node_data = _extract_node_data(node) if node else {}
                target_node_type = _node_type_slug(node) if node else None
                target_node_content = _resolve_node_text(target_node_data) if node else None
                logger.info(
                    "[CHOICE TARGET EXECUTION START] flow_id=%s session_id=%s target_node_id=%s target_node_type=%s target_node_content=%s",
                    flow.id,
                    getattr(flow_session, "id", None),
                    next_node_id,
                    target_node_type,
                    target_node_content,
                )
                logger.info(
                    "[CHOICE TARGET NODE LOADED] flow_id=%s session_id=%s target_node_id=%s target_node_type=%s target_node_content=%s",
                    flow.id,
                    getattr(flow_session, "id", None),
                    next_node_id,
                    target_node_type,
                    target_node_content,
                )
                choice_target_trace = {
                    "target_node_id": str(next_node_id) if next_node_id else None,
                    "target_node_type": target_node_type,
                    "target_node_content": target_node_content,
                }
                _log_choice_runtime_marker(
                    "[CHOICE FLOW CONTINUE]",
                    session_id=getattr(flow_session, "id", None),
                    current_node_id=current_node_uuid,
                    choice_node_id=current_node_uuid,
                    selected_row_id=selected_handle,
                    target_node_id=next_node_id,
                    correlation_id=correlation_id,
                )
                logger.info(
                    "[CHOICE FLOW CONTINUE DETAIL] flow_id=%s session_id=%s source_handle=%s target_node=%s next_node_type=%s",
                    flow.id, getattr(flow_session, "id", None), selected_handle, next_node_id, _node_type_slug(node) if node else None,
                )
                normalized_input = ""
                continue

            tenant = db.get(Tenant, session.tenant_id)
            phone = getattr(session, "phone_number", None) or getattr(session, "user_identifier", None)
            if tenant and phone and choice_body_text and choice_sections:
                _send_flow_interactive_list(
                    tenant=tenant,
                    phone=phone,
                    text=choice_body_text,
                    sections=choice_sections,
                    options=choice_options,
                    flow_id=flow.id,
                    flow_version_id=getattr(flow_session, "flow_version_id", None),
                    session_id=getattr(flow_session, "id", None) or session.id,
                    node_id=current_node_uuid,
                    node_type=node_type,
                    flow_engine="legacy",
                    flow_executor="run_until_wait_node",
                    flow_send_source="run_until_wait_node:choice",
                )
            _log_session_node_transition(
                "BEFORE",
                flow_session=flow_session,
                conversation=session,
                executed_node_id=_node_get(node, "id"),
                next_node_id=current_node_uuid,
                reason="waiting_choice",
            )
            if flow_session:
                flow_session.current_node_id = session_service.safe_update_current_node(
                    session=flow_session,
                    next_node_id=current_node_uuid,
                    reason="waiting_choice",
                    graph_context={"executed_node_id": str(_node_get(node, "id")) if _node_get(node, "id") else None},
                )
                flow_session.context = {**(flow_session.context or {}), "waiting_choice": True, "choice_node_id": str(current_node_uuid) if current_node_uuid else None, "choice_options": choice_options}
                db.add(flow_session)
            if isinstance(session.context, dict):
                session.context["flow_current_node_id"] = str(current_node_uuid) if current_node_uuid else None
                session.context["waiting_choice"] = True
            _log_session_node_transition(
                "AFTER",
                flow_session=flow_session,
                conversation=session,
                executed_node_id=_node_get(node, "id"),
                next_node_id=current_node_uuid,
                reason="waiting_choice",
            )
            db.add(session)
            db.commit()
            _log_session_node_transition(
                "PERSIST",
                flow_session=flow_session,
                conversation=session,
                executed_node_id=_node_get(node, "id"),
                next_node_id=current_node_uuid,
                reason="waiting_choice",
            )
            return node

        if node_type in {"buttons", "buttons_node"}:
            raw_buttons = node_data.get("buttons") if isinstance(node_data.get("buttons"), list) else []
            buttons = [button for button in raw_buttons[:3] if isinstance(button, dict) and str(button.get("label") or button.get("title") or "").strip()]
            selected_handle = None
            for index, button in enumerate(buttons):
                label = str(button.get("label") or button.get("title") or "").strip()
                handle = str(button.get("handleId") or button.get("id") or _normalize_text(label).replace(" ", "_") or f"button_{index + 1}")
                if normalized_input and (_normalize_text(label) == normalized_input or _normalize_text(handle) == normalized_input):
                    selected_handle = handle
                    _emit_runtime_event(
                        db=db, tenant_id=session.tenant_id, conversation_id=session.id, flow_id=flow.id,
                        flow_version_id=getattr(flow_session, "flow_version_id", None), node_id=current_node_uuid,
                        event_type="BUTTON_CLICKED", metadata={"option_id": selected_handle, "label": label}, dedupe_bucket_seconds=1,
                    )
                    break
            if selected_handle:
                next_node_id = _edge_target(next((edge for edge in edges if _edge_source_handle(edge) == selected_handle), None))
                logger.info(
                    "[NEXT NODE RESOLVED] flow_id=%s session_id=%s current_node_id=%s next_node_id=%s node_type=%s",
                    flow.id, getattr(flow_session, "id", None), _node_get(node, "id"), next_node_id, node_type,
                )
                logger.info(
                    "[NODE COMPLETE] flow_id=%s session_id=%s current_node_id=%s next_node_id=%s node_type=%s",
                    flow.id, getattr(flow_session, "id", None), _node_get(node, "id"), next_node_id, node_type,
                )
                node = _get_node(db=db, node_id=next_node_id, tenant_id=session.tenant_id, runtime_graph=runtime_graph)
                logger.info(
                    "[NEXT NODE EXECUTE] flow_id=%s session_id=%s current_node_id=%s next_node_id=%s node_type=%s",
                    flow.id, getattr(flow_session, "id", None), _node_get(node, "id") if node else None, None, _node_type_slug(node) if node else None,
                )
                normalized_input = ""
                continue
            tenant = db.get(Tenant, session.tenant_id)
            phone = getattr(session, "phone_number", None) or getattr(session, "user_identifier", None)
            body_text = str(node_data.get("body_text") or node_data.get("content") or "").strip()
            if tenant and phone and body_text and buttons:
                _send_flow_interactive_buttons(tenant=tenant, phone=phone, text=body_text, buttons=buttons, flow_id=flow.id, flow_version_id=getattr(flow_session, "flow_version_id", None), session_id=session.id, node_id=current_node_uuid, node_type=node_type)
            _log_session_node_transition(
                "BEFORE",
                flow_session=flow_session,
                conversation=session,
                executed_node_id=_node_get(node, "id"),
                next_node_id=current_node_uuid,
                reason="buttons_waiting_input",
            )
            if flow_session:
                flow_session.current_node_id = session_service.safe_update_current_node(
                    session=flow_session,
                    next_node_id=current_node_uuid,
                    reason="buttons_waiting_input",
                    graph_context={"executed_node_id": str(_node_get(node, "id")) if _node_get(node, "id") else None},
                )
                db.add(flow_session)
            _log_session_node_transition(
                "AFTER",
                flow_session=flow_session,
                conversation=session,
                executed_node_id=_node_get(node, "id"),
                next_node_id=current_node_uuid,
                reason="buttons_waiting_input",
            )
            db.commit()
            _log_session_node_transition(
                "PERSIST",
                flow_session=flow_session,
                conversation=session,
                executed_node_id=_node_get(node, "id"),
                next_node_id=current_node_uuid,
                reason="buttons_waiting_input",
            )
            return node

        if node_type in {"list", "list_node"}:
            sections = node_data.get("sections") if isinstance(node_data.get("sections"), list) else []
            if not sections and isinstance(node_data.get("rows"), list):
                sections = [{"title": "Opções", "rows": node_data.get("rows")}]
            selected_handle = None
            for section in sections:
                if not isinstance(section, dict):
                    continue
                for index, row in enumerate([row for row in section.get("rows", []) if isinstance(row, dict)]):
                    label = str(row.get("title") or row.get("label") or "").strip()
                    handle = str(row.get("handleId") or row.get("id") or _normalize_text(label).replace(" ", "_") or f"row_{index + 1}")
                    if normalized_input and (_normalize_text(label) == normalized_input or _normalize_text(handle) == normalized_input):
                        selected_handle = handle
                        _emit_runtime_event(
                            db=db, tenant_id=session.tenant_id, conversation_id=session.id, flow_id=flow.id,
                            flow_version_id=getattr(flow_session, "flow_version_id", None), node_id=current_node_uuid,
                            event_type="LIST_SELECTED", metadata={"option_id": selected_handle, "label": label}, dedupe_bucket_seconds=1,
                        )
                        break
                if selected_handle:
                    break
            if selected_handle:
                next_node_id = _edge_target(next((edge for edge in edges if _edge_source_handle(edge) == selected_handle), None))
                logger.info(
                    "[NEXT NODE RESOLVED] flow_id=%s session_id=%s current_node_id=%s next_node_id=%s node_type=%s",
                    flow.id, getattr(flow_session, "id", None), _node_get(node, "id"), next_node_id, node_type,
                )
                logger.info(
                    "[NODE COMPLETE] flow_id=%s session_id=%s current_node_id=%s next_node_id=%s node_type=%s",
                    flow.id, getattr(flow_session, "id", None), _node_get(node, "id"), next_node_id, node_type,
                )
                node = _get_node(db=db, node_id=next_node_id, tenant_id=session.tenant_id, runtime_graph=runtime_graph)
                logger.info(
                    "[NEXT NODE EXECUTE] flow_id=%s session_id=%s current_node_id=%s next_node_id=%s node_type=%s",
                    flow.id, getattr(flow_session, "id", None), _node_get(node, "id") if node else None, None, _node_type_slug(node) if node else None,
                )
                normalized_input = ""
                continue
            phone = getattr(session, "phone_number", None) or getattr(session, "user_identifier", None)
            body_text = str(node_data.get("body_text") or node_data.get("content") or "").strip()
            if phone and body_text and sections:
                send_whatsapp_list_cloud(phone, body_text, sections, tenant_id=str(session.tenant_id))
            _log_session_node_transition(
                "BEFORE",
                flow_session=flow_session,
                conversation=session,
                executed_node_id=_node_get(node, "id"),
                next_node_id=current_node_uuid,
                reason="list_waiting_input",
            )
            if flow_session:
                flow_session.current_node_id = session_service.safe_update_current_node(
                    session=flow_session,
                    next_node_id=current_node_uuid,
                    reason="list_waiting_input",
                    graph_context={"executed_node_id": str(_node_get(node, "id")) if _node_get(node, "id") else None},
                )
                db.add(flow_session)
            _log_session_node_transition(
                "AFTER",
                flow_session=flow_session,
                conversation=session,
                executed_node_id=_node_get(node, "id"),
                next_node_id=current_node_uuid,
                reason="list_waiting_input",
            )
            db.commit()
            _log_session_node_transition(
                "PERSIST",
                flow_session=flow_session,
                conversation=session,
                executed_node_id=_node_get(node, "id"),
                next_node_id=current_node_uuid,
                reason="list_waiting_input",
            )
            return node

        if node_type == "condition":
            if not normalized_input:
                target_node_id = _parse_uuid(_node_get(node, "id"))
                _log_session_node_transition(
                    "BEFORE",
                    flow_session=flow_session,
                    conversation=session,
                    executed_node_id=_node_get(node, "id"),
                    next_node_id=target_node_id,
                    reason="continue_condition_waiting_input",
                )
                if flow_session:
                    flow_session.current_node_id = session_service.safe_update_current_node(
                        session=flow_session,
                        next_node_id=target_node_id,
                        reason="continue_condition_waiting_input",
                        graph_context={"executed_node_id": str(_node_get(node, "id")) if _node_get(node, "id") else None},
                    )
                    flow_session.last_input = incoming_text
                    db.add(flow_session)
                if isinstance(session.context, dict):
                    session.context["flow_current_node_id"] = str(target_node_id) if target_node_id else None
                _log_session_node_transition(
                    "AFTER",
                    flow_session=flow_session,
                    conversation=session,
                    executed_node_id=_node_get(node, "id"),
                    next_node_id=target_node_id,
                    reason="continue_condition_waiting_input",
                )
                logger.info(
                    "[FLOW SESSION CURRENT_NODE PERSISTED] session_current_node_id=%s conversation_fk_skipped=true",
                    target_node_id,
                )
                db.add(session)
                db.commit()
                _log_session_node_transition(
                    "PERSIST",
                    flow_session=flow_session,
                    conversation=session,
                    executed_node_id=_node_get(node, "id"),
                    next_node_id=target_node_id,
                    reason="continue_condition_waiting_input",
                )
                logger.info("[MANYCHAT WAITING_INPUT] node_id=%s", _node_get(node, "id"))
                return node
            true_edge, false_edge = _resolve_condition_routes(edges)
            raw_condition = str(node_data.get("condition") or node_data.get("content") or "")
            keywords = [_normalize_text(kw) for kw in raw_condition.split(",") if _normalize_text(kw)]
            matched = bool(_match_condition_input(normalized_input, keywords))
            selected_edge = true_edge if matched else false_edge
            matched_handle = _edge_source_handle(selected_edge) if selected_edge else None
            target_node_id = _edge_target(selected_edge) if selected_edge else None
            logger.info(
                "[CONDITION EVALUATED] condition_node_id=%s incoming_text=%s matched=%s branch=%s matched_handle=%s target_node_id=%s",
                _node_get(node, "id"),
                incoming_text,
                matched,
                "true" if matched else "false",
                matched_handle,
                target_node_id,
            )
            logger.info("[MANYCHAT ADVANCE] from=%s to=%s", _node_get(node, "id"), target_node_id)
            logger.info(
                "[NEXT NODE RESOLVED] flow_id=%s session_id=%s current_node_id=%s next_node_id=%s node_type=%s",
                flow.id, getattr(flow_session, "id", None), _node_get(node, "id"), target_node_id, node_type,
            )
            logger.info(
                "[NODE COMPLETE] flow_id=%s session_id=%s current_node_id=%s next_node_id=%s node_type=%s",
                flow.id, getattr(flow_session, "id", None), _node_get(node, "id"), target_node_id, node_type,
            )
            node = _get_node(db=db, node_id=target_node_id, tenant_id=session.tenant_id, runtime_graph=runtime_graph) if selected_edge else None
            logger.info(
                "[NEXT NODE EXECUTE] flow_id=%s session_id=%s current_node_id=%s next_node_id=%s node_type=%s",
                flow.id, getattr(flow_session, "id", None), _node_get(node, "id") if node else None, None, _node_type_slug(node) if node else None,
            )
            normalized_input = ""
            continue

        if node_type in {"message", "text", "msg", "start", "delay", "action", "image", "image_node", "document", "document_node"}:
            if node_type == "delay":
                delay_seconds = int(float(str(node_data.get("delay") or node_data.get("seconds") or node_data.get("content") or 0)))
                next_edge = _pick_default_edge(edges)
                next_target = _edge_target(next_edge) if next_edge else None
                if delay_seconds > 0 and next_target:
                    enqueue_delay(
                        session.tenant_id,
                        str(session.phone_number or session.user_identifier or ""),
                        _parse_uuid(next_target),
                        delay_seconds,
                        flow_id=flow.id,
                        flow_session_id=getattr(flow_session, "id", None),
                        flow_version_id=getattr(flow_session, "flow_version_id", None),
                        delay_node_id=_parse_uuid(_node_get(node, "id")),
                        expected_current_node_id=_parse_uuid(_node_get(node, "id")),
                    )
                    logger.info("[DELAY SCHEDULED] delay_node_id=%s seconds=%s next_node_id=%s", _node_get(node, "id"), delay_seconds, next_target)
                    if flow_session:
                        delay_current_node_id = _parse_uuid(_node_get(node, "id"))
                        logger.info(
                            "[DELAY CURRENT NODE PRESERVED] session_id=%s delay_node_id=%s scheduled_next_node_id=%s reason=waiting_delay",
                            getattr(flow_session, "id", None),
                            delay_current_node_id,
                            next_target,
                        )
                        flow_session.current_node_id = session_service.safe_update_current_node(
                            session=flow_session,
                            next_node_id=delay_current_node_id,
                            reason="waiting_delay",
                            graph_context={"executed_node_id": str(_node_get(node, "id"))},
                        )
                        flow_session.context = {
                            **(flow_session.context or {}),
                            "waiting_delay": True,
                            "delay_node_id": str(delay_current_node_id) if delay_current_node_id else None,
                            "pending_delay_next_node_id": str(next_target) if next_target else None,
                        }
                        db.add(flow_session)
                    db.commit()
                    return None
            if node_type in {"image", "image_node"}:
                media_url = str(node_data.get("media_url") or node_data.get("url") or "").strip()
                caption = str(node_data.get("caption") or "").strip()
                phone = getattr(session, "phone_number", None) or getattr(session, "user_identifier", None)
                if phone and media_url:
                    send_whatsapp_image_cloud(phone, media_url, caption, tenant_id=str(session.tenant_id))
                    logger.info("[MANYCHAT IMAGE SENT] node_id=%s", _node_get(node, "id"))
            if node_type in {"document", "document_node"}:
                document_url = str(node_data.get("document_url") or node_data.get("url") or "").strip()
                filename = str(node_data.get("filename") or "").strip()
                caption = str(node_data.get("caption") or "").strip()
                phone = getattr(session, "phone_number", None) or getattr(session, "user_identifier", None)
                if phone and document_url:
                    send_whatsapp_document_cloud(phone, document_url, filename, caption, tenant_id=str(session.tenant_id))
                    logger.info("[MANYCHAT DOCUMENT SENT] node_id=%s", _node_get(node, "id"))
            if node_type in {"message", "text", "msg"}:
                text = _resolve_node_text(node_data)
                if text:
                    tenant = db.get(Tenant, session.tenant_id)
                    if tenant:
                        phone = getattr(session, "phone_number", None) or getattr(session, "user_identifier", None)
                        if not phone:
                            logger.warning("[MANYCHAT SEND FAILED] reason=missing_phone node_id=%s", _node_get(node, "id"))
                            next_edge = _pick_default_edge(edges)
                            logger.info("[MANYCHAT ADVANCE] from=%s to=%s", _node_get(node, "id"), _edge_target(next_edge) if next_edge else None)
                            node = _get_node(db=db, node_id=_edge_target(next_edge), tenant_id=session.tenant_id, runtime_graph=runtime_graph) if next_edge else None
                            continue
                        _send_flow_whatsapp_message(
                            tenant=tenant,
                            phone=phone,
                            text=text,
                            flow_id=flow.id,
                            flow_version_id=getattr(flow_session, "flow_version_id", None),
                            session_id=getattr(flow_session, "id", None),
                            node_id=current_node_uuid,
                            node_type=node_type,
                            flow_engine="legacy",
                            flow_executor="run_until_wait_node",
                            flow_send_source="run_until_wait_node:message",
                        )
                        logger.info("[MANYCHAT MESSAGE SENT] node_id=%s", _node_get(node, "id"))
                        if choice_target_trace and choice_target_trace.get("target_node_id") == str(current_node_uuid):
                            logger.info(
                                "[CHOICE TARGET MESSAGE SENT] flow_id=%s session_id=%s target_node_id=%s target_node_type=%s target_node_content=%s",
                                flow.id,
                                getattr(flow_session, "id", None),
                                current_node_uuid,
                                node_type,
                                text,
                            )
            next_edge = _pick_default_edge(edges)
            next_target = _edge_target(next_edge) if next_edge else None
            message_node_id = _node_get(node, "id")
            next_node = _get_node(db=db, node_id=next_target, tenant_id=session.tenant_id, runtime_graph=runtime_graph) if next_edge and next_target else None
            logger.info(
                "[FLOW EDGE RESOLUTION] current_node=%s edge_count=%s outgoing_edges=%s next_node=%s",
                message_node_id,
                len(edges),
                [
                    {
                        "id": str(_node_get(edge, "id")),
                        "source": str(_edge_source(edge)),
                        "target": str(_edge_target(edge)),
                        "sourceHandle": _edge_source_handle(edge),
                    }
                    for edge in edges
                ],
                _node_get(next_node, "id") if next_node else None,
            )
            logger.info(
                "[EDGE RESOLUTION] flow_id=%s flow_version_id=%s current_node=%s edge_count=%s next_target=%s next_node=%s nodes_by_id_keys=%s",
                flow.id,
                getattr(flow_session, "flow_version_id", None),
                message_node_id,
                len(edges),
                next_target,
                _node_get(next_node, "id") if next_node else None,
                list((runtime_graph.get("node_map") if isinstance(runtime_graph, dict) and isinstance(runtime_graph.get("node_map"), dict) else {}).keys()),
            )
            if next_target:
                _emit_runtime_event(
                    db=db,
                    tenant_id=session.tenant_id,
                    conversation_id=session.id,
                    flow_id=flow.id,
                    flow_version_id=getattr(flow_session, "flow_version_id", None),
                    node_id=current_node_uuid,
                    event_type="NODE_EXITED",
                    metadata={"source": "default_edge", "next_node_id": str(next_target)},
                    dedupe_bucket_seconds=1,
                )
            if _is_terminal_message_node(node_data) and not next_node:
                _emit_runtime_event(
                    db=db,
                    tenant_id=session.tenant_id,
                    conversation_id=session.id,
                    flow_id=flow.id,
                    flow_version_id=getattr(flow_session, "flow_version_id", None),
                    node_id=current_node_uuid,
                    event_type="NODE_EXITED",
                    metadata={"source": "terminal_message"},
                    dedupe_bucket_seconds=1,
                )
                logger.info(
                    "[FLOW FINISH CHECK] reason=%s current_node=%s next_node=%s",
                    "terminal_message_without_next_node",
                    _node_get(node, "id"),
                    None,
                )
                logger.info(
                    "[NODE COMPLETE] flow_id=%s session_id=%s current_node_id=%s next_node_id=%s node_type=%s",
                    flow.id, getattr(flow_session, "id", None), _node_get(node, "id"), None, node_type,
                )
                _finalize_runtime_flow_session(db=db, conversation=session, flow_session=flow_session, end_node_id=_node_get(node, "id"))
                if choice_target_trace and choice_target_trace.get("target_node_id") == str(current_node_uuid):
                    logger.info(
                        "[CHOICE TARGET EXECUTION FINISHED] flow_id=%s session_id=%s target_node_id=%s target_node_type=%s target_node_content=%s",
                        flow.id,
                        getattr(flow_session, "id", None),
                        current_node_uuid,
                        node_type,
                        choice_target_trace.get("target_node_content"),
                    )
                return None
            next_node_type = _node_type_slug(next_node) if next_node else None
            logger.info(
                "[NEXT NODE FOUND] flow_id=%s session_id=%s current_node_id=%s next_node_id=%s next_node_type=%s source=%s",
                flow.id,
                getattr(flow_session, "id", None),
                message_node_id,
                next_target,
                next_node_type,
                "run_until_wait_node:message_default_edge",
            )
            logger.info(
                "[MESSAGE POST ADVANCE] message_node_id=%s next_node_id=%s next_node_type=%s",
                message_node_id,
                next_target,
                next_node_type,
            )
            logger.info(
                "[NEXT NODE RESOLVED] flow_id=%s session_id=%s current_node_id=%s next_node_id=%s node_type=%s",
                flow.id, getattr(flow_session, "id", None), message_node_id, next_target, node_type,
            )
            logger.info(
                "[NODE COMPLETE] flow_id=%s session_id=%s current_node_id=%s next_node_id=%s node_type=%s",
                flow.id, getattr(flow_session, "id", None), message_node_id, next_target, node_type,
            )
            logger.info("[MANYCHAT ADVANCE] from=%s to=%s", message_node_id, next_target)
            node = next_node
            logger.info(
                "[NEXT NODE EXECUTE] flow_id=%s session_id=%s current_node_id=%s next_node_id=%s node_type=%s",
                flow.id, getattr(flow_session, "id", None), _node_get(node, "id") if node else None, None, _node_type_slug(node) if node else None,
            )
            logger.info(
                "[EXECUTING NEXT NODE] flow_id=%s session_id=%s current_node_id=%s next_node_id=%s next_node_type=%s source=%s",
                flow.id,
                getattr(flow_session, "id", None),
                message_node_id,
                _node_get(node, "id") if node else None,
                _node_type_slug(node) if node else None,
                "run_until_wait_node:message_default_edge",
            )
            if choice_target_trace and choice_target_trace.get("target_node_id") == str(current_node_uuid):
                logger.info(
                    "[CHOICE TARGET EXECUTION FINISHED] flow_id=%s session_id=%s target_node_id=%s target_node_type=%s target_node_content=%s",
                    flow.id,
                    getattr(flow_session, "id", None),
                    current_node_uuid,
                    node_type,
                    choice_target_trace.get("target_node_content"),
                )
                choice_target_trace = None
            if node and next_node_type == "condition":
                condition_node_id = _node_get(node, "id")
                target_node_id = _parse_uuid(condition_node_id)
                _log_session_node_transition(
                    "BEFORE",
                    flow_session=flow_session,
                    conversation=session,
                    executed_node_id=message_node_id,
                    next_node_id=target_node_id,
                    reason="message_advance_to_condition",
                )
                if flow_session:
                    flow_session.current_node_id = session_service.safe_update_current_node(
                        session=flow_session,
                        next_node_id=target_node_id,
                        reason="message_advance_to_condition",
                        graph_context={"executed_node_id": str(message_node_id) if message_node_id else None},
                    )
                    flow_session.last_input = incoming_text
                    db.add(flow_session)
                if isinstance(session.context, dict):
                    session.context["flow_current_node_id"] = str(target_node_id) if target_node_id else None
                _log_session_node_transition(
                    "AFTER",
                    flow_session=flow_session,
                    conversation=session,
                    executed_node_id=message_node_id,
                    next_node_id=target_node_id,
                    reason="message_advance_to_condition",
                )
                logger.info(
                    "[FLOW SESSION CURRENT_NODE PERSISTED] session_current_node_id=%s conversation_fk_skipped=true",
                    target_node_id,
                )
                db.add(session)
                db.commit()
                _log_session_node_transition(
                    "PERSIST",
                    flow_session=flow_session,
                    conversation=session,
                    executed_node_id=message_node_id,
                    next_node_id=target_node_id,
                    reason="message_advance_to_condition",
                )
                logger.info(
                    "[WAITING_NEXT_CONDITION] condition_node_id=%s from_message_node_id=%s",
                    condition_node_id,
                    message_node_id,
                )
                return node
            continue

        if _is_wait_node_type(node_type):
            target_node_id = _parse_uuid(_node_get(node, "id"))
            _log_session_node_transition(
                "BEFORE",
                flow_session=flow_session,
                conversation=session,
                executed_node_id=_node_get(node, "id"),
                next_node_id=target_node_id,
                reason="wait_node",
            )
            if flow_session:
                flow_session.current_node_id = session_service.safe_update_current_node(
                    session=flow_session,
                    next_node_id=target_node_id,
                    reason="wait_node",
                    graph_context={"executed_node_id": str(_node_get(node, "id")) if _node_get(node, "id") else None},
                )
                flow_session.last_input = incoming_text
                db.add(flow_session)
            if isinstance(session.context, dict):
                session.context["flow_current_node_id"] = str(target_node_id) if target_node_id else None
            _log_session_node_transition(
                "AFTER",
                flow_session=flow_session,
                conversation=session,
                executed_node_id=_node_get(node, "id"),
                next_node_id=target_node_id,
                reason="wait_node",
            )
            logger.info(
                "[FLOW SESSION CURRENT_NODE PERSISTED] session_current_node_id=%s conversation_fk_skipped=true",
                target_node_id,
            )
            db.add(session)
            db.commit()
            _log_session_node_transition(
                "PERSIST",
                flow_session=flow_session,
                conversation=session,
                executed_node_id=_node_get(node, "id"),
                next_node_id=target_node_id,
                reason="wait_node",
            )
            logger.info("[MANYCHAT WAITING_INPUT] node_id=%s", _node_get(node, "id"))
            return node

        next_edge = _pick_default_edge(edges)
        node = _get_node(db=db, node_id=_edge_target(next_edge), tenant_id=session.tenant_id, runtime_graph=runtime_graph) if next_edge else None

    logger.info(
        "[FLOW FINISH CHECK] reason=%s current_node=%s next_node=%s",
        "no_next_node_or_max_steps",
        _node_get(node, "id") if node else None,
        None,
    )
    _finalize_runtime_flow_session(db=db, conversation=session, flow_session=flow_session, end_node_id=_node_get(node, "id") if node else None)
    logger.info("[MANYCHAT FLOW_FINISHED] flow_id=%s", flow.id)
    return None


def advance_after_message_node(
    *,
    db: Session,
    conversation: Conversation,
    flow: Flow,
    current_node: FlowNode | VersionedFlowNode,
    runtime_graph: dict[str, Any],
    session_service: FlowSessionService,
    user_identifier: str,
    context: dict[str, Any],
    published_version_number: int | None,
) -> tuple[FlowNode | VersionedFlowNode | None, FlowSession]:
    current_node_id = _node_get(current_node, "id")
    edges = _get_edges(db=db, flow_id=flow.id, source=current_node_id, runtime_graph=runtime_graph)
    if not edges and isinstance(runtime_graph, dict):
        all_edges = runtime_graph.get("edges") if isinstance(runtime_graph.get("edges"), list) else []
        current_node_id_str = str(current_node_id)
        edges = [edge for edge in all_edges if str(_edge_source(edge)) == current_node_id_str]
    next_edge = _pick_default_edge(edges)
    next_target = _edge_target(next_edge) if next_edge else None
    preview_next_node = _get_node(db=db, node_id=next_target, tenant_id=conversation.tenant_id, runtime_graph=runtime_graph) if next_edge and next_target else None
    logger.info(
        "[FLOW EDGE RESOLUTION] current_node=%s edge_count=%s outgoing_edges=%s next_node=%s",
        current_node_id,
        len(edges),
        [
            {
                "id": str(_node_get(edge, "id")),
                "source": str(_edge_source(edge)),
                "target": str(_edge_target(edge)),
                "sourceHandle": _edge_source_handle(edge),
            }
            for edge in edges
        ],
        _node_get(preview_next_node, "id") if preview_next_node else None,
    )
    runtime_node_map = runtime_graph.get("node_map") if isinstance(runtime_graph, dict) and isinstance(runtime_graph.get("node_map"), dict) else {}
    logger.info(
        "[EDGE RESOLUTION] flow_id=%s flow_version_id=%s current_node=%s edge_count=%s next_target=%s next_node=%s nodes_by_id_keys=%s",
        flow.id,
        runtime_graph.get("version_id") if isinstance(runtime_graph, dict) else None,
        current_node_id,
        len(edges),
        next_target,
        _node_get(preview_next_node, "id") if preview_next_node else None,
        list(runtime_node_map.keys()),
    )
    if not next_edge or not next_target:
        logger.info(
            "[FLOW FINISH CHECK] reason=%s current_node=%s next_node=%s",
            "missing_message_next_edge",
            current_node_id,
            None,
        )
        logger.error(
            "[FLOW EDGE LOOKUP FAILED] current_node_id=%s edges_count=%s edges_raw=%s node_ids=%s published_version_id=%s flow_id=%s",
            current_node_id,
            len(edges),
            edges,
            [str(_node_get(n, "id")) for n in (runtime_graph.get("nodes") if isinstance(runtime_graph, dict) and isinstance(runtime_graph.get("nodes"), list) else [])],
            getattr(flow, "published_version_id", None),
            flow.id,
        )
        logger.warning("[FLOW STUCK_NO_EDGE] current_node_id=%s flow_id=%s", current_node_id, flow.id)
        return None, session_service.get_runtime_session(conversation.tenant_id, user_identifier, flow)
    nodes = runtime_graph.get("nodes") if isinstance(runtime_graph, dict) and isinstance(runtime_graph.get("nodes"), list) else []
    node_map = build_node_map(nodes)
    next_target_str = str(next_target)
    target_node = node_map.get(next_target_str) or _get_node(
        db=db,
        node_id=next_target,
        tenant_id=conversation.tenant_id,
        runtime_graph=runtime_graph,
    )
    if not target_node:
        logger.error(
            "[FLOW TARGET LOOKUP FAILED] next_target=%s next_target_type=%s node_map_keys=%s nodes_raw_preview=%s",
            next_target_str,
            type(next_target).__name__,
            list(node_map.keys()),
            [
                {"id": _node_id(node), "type": _node_get(node, "type")}
                for node in nodes[:10]
            ],
        )
        raise RuntimeError(f"Message node target not found: {next_target}")
    logger.info(
        "[FLOW TARGET FOUND] target_id=%s target_type=%s",
        next_target_str,
        _node_get(target_node, "type"),
    )
    logger.info(
        "[NEXT NODE FOUND] flow_id=%s session_id=%s current_node_id=%s next_node_id=%s next_node_type=%s source=%s",
        flow.id,
        None,
        current_node_id,
        next_target_str,
        _node_type_slug(target_node),
        "advance_after_message_node",
    )
    _safe_set_conversation_current_node(db, conversation, next_target)
    runtime_session = session_service.save_runtime_session(
        tenant_id=conversation.tenant_id,
        user_identifier=user_identifier,
        flow=flow,
        current_node_id=next_target,
        context=context,
        status="running",
        variables={"flow_version": published_version_number},
        executed_node_id=current_node_id,
        next_node_id=next_target,
    )
    db.commit()
    logger.info(
        "[FORCED MESSAGE ADVANCE] from=%s to=%s to_type=%s",
        current_node_id,
        next_target,
        _node_type_slug(target_node),
    )
    logger.warning(
        "[NEXT NODE RETURN INTERRUPT] return=advance_after_message_node:target_node_runtime_session current_node_id=%s next_node_id=%s next_node_type=%s detail=%s",
        current_node_id,
        next_target,
        _node_type_slug(target_node),
        "caller must continue execution or the saved next node will not run immediately",
    )
    return target_node, runtime_session
def _is_continuation_message(incoming_text: str | None, runtime_session: FlowSession | None) -> bool:
    return bool((incoming_text or "").strip()) and runtime_session is not None


def _send_start_message_on_session_restart(
    *,
    db: Session,
    tenant: Tenant,
    conversation: Conversation,
    flow: FlowDefinition,
    start_node: FlowNode | VersionedFlowNode,
    runtime_graph: dict[str, Any],
    runtime_session: FlowSession | None,
    session_service: FlowSessionService,
    published_version_number: int | None,
    user_identifier: str,
    incoming_text: str | None = None,
    reason: str = "session_restart",
) -> FlowSession | None:
    node_data = _extract_node_data(start_node)
    node_type = str(_node_get(start_node, "type") or "").strip().lower()
    if node_type.endswith("_node"):
        node_type = node_type[:-5]
    elif node_type.endswith("node"):
        node_type = node_type[:-4]

    start_node_id = _node_get(start_node, "id")
    logger.info(
        "[START SEND ATTEMPT] incoming_text_present=%s session_id=%s current_node_id=%s reason=%s",
        bool((incoming_text or "").strip()),
        getattr(runtime_session, "id", None),
        getattr(runtime_session, "current_node_id", None) if runtime_session else conversation.current_node_id,
        reason,
    )
    incoming_text_present = bool((incoming_text or "").strip())
    active_session_id = getattr(runtime_session, "id", None)
    active_current_node_id = getattr(runtime_session, "current_node_id", None) if runtime_session else conversation.current_node_id
    session_status = str(getattr(runtime_session, "status", "") or "").strip().lower()
    has_recoverable_state = bool(_parse_uuid(active_current_node_id))

    if incoming_text_present and runtime_session is not None:
        if session_status in {"active", "running"} and has_recoverable_state:
            logger.warning("[START SEND HARD_BLOCKED_CONTINUATION] session_id=%s", active_session_id)
            return None
        if session_status in {"active", "running"} and not has_recoverable_state:
            logger.warning("[FLOW CONTINUATION LOST_STATE] session_id=%s incoming_text_present=true", active_session_id)
            return None
        if session_status in {"expired", "finalized", "completed", "finished"} and not has_recoverable_state:
            logger.info("[START SEND ALLOWED_EXPIRED_NO_STATE] session_id=%s status=%s", active_session_id, session_status)

    logger.info(
        "[START SEND ALLOWED_INITIAL_MESSAGE] incoming_text_present=%s session_id=%s current_node_id=%s",
        incoming_text_present,
        active_session_id,
        active_current_node_id,
    )

    logger.info("[FLOW START MESSAGE ATTEMPT] node_id=%s node_type=%s", start_node_id, node_type)

    if node_type == "message":
        text = _resolve_node_text(node_data)
        job_id = _send_flow_whatsapp_message(
            tenant=tenant,
            phone=conversation.phone_number,
            text=text,
            flow_id=flow.id,
            flow_version_id=getattr(runtime_session, "flow_version_id", None),
            session_id=getattr(runtime_session, "id", None),
            node_id=start_node_id,
            node_type=node_type,
            flow_engine="legacy",
            flow_executor="_send_start_message_on_session_restart",
            flow_send_source="_send_start_message_on_session_restart:start_message",
        )
        if not job_id:
            logger.error("[FLOW START MESSAGE NOT SENT] node_id=%s", start_node_id)
            runtime_session = session_service.save_runtime_session(
                tenant_id=conversation.tenant_id,
                user_identifier=user_identifier,
                flow=flow,
                current_node_id=start_node_id,
                context=conversation.context if isinstance(conversation.context, dict) else {},
                status="running",
                variables={"flow_version": published_version_number},
                executed_node_id=start_node_id,
                next_node_id=start_node_id,
            )
            return runtime_session
        logger.info(
            "[FLOW START MESSAGE SENT] node_id=%s text_preview=%s",
            start_node_id,
            _text_preview(text),
        )
        logger.info("[START MESSAGE BEFORE SESSION SAVE] node_id=%s", start_node_id)

    if node_type == "message":
        next_node, runtime_session = advance_after_message_node(
            db=db,
            conversation=conversation,
            flow=flow,
            current_node=start_node,
            runtime_graph=runtime_graph,
            session_service=session_service,
            user_identifier=user_identifier,
            context=conversation.context if isinstance(conversation.context, dict) else {},
            published_version_number=published_version_number,
        )
        next_node_id = _parse_uuid(_node_get(next_node, "id")) if next_node else None
        next_node_type = _node_type_slug(next_node) if next_node else None
        logger.info(
            "[EXECUTING NEXT NODE] flow_id=%s session_id=%s current_node_id=%s next_node_id=%s next_node_type=%s source=%s",
            flow.id,
            getattr(runtime_session, "id", None),
            start_node_id,
            next_node_id,
            next_node_type,
            "_send_start_message_on_session_restart",
        )
        if next_node_id is None:
            logger.warning(
                "[NEXT NODE RETURN INTERRUPT] return=_send_start_message_on_session_restart:return_runtime_session reason=missing_next_node current_node_id=%s",
                start_node_id,
            )
            return runtime_session
        run_until_wait_node(
            db=db,
            flow=flow,
            runtime_graph=runtime_graph,
            session=conversation,
            start_node_id=next_node_id,
            incoming_text=None,
        )
        return runtime_session

    runtime_session = session_service.save_runtime_session(
        tenant_id=conversation.tenant_id,
        user_identifier=user_identifier,
        flow=flow,
        current_node_id=start_node_id,
        context=conversation.context if isinstance(conversation.context, dict) else {},
        status="running",
        variables={"flow_version": published_version_number},
        executed_node_id=start_node_id,
        next_node_id=start_node_id,
    )
    return runtime_session
def process_flow_engine(
    db: Session,
    tenant_id: uuid.UUID,
    phone: str,
    message_text: str = "",
    force_node: uuid.UUID | None = None,
    flow_id: str | None = None,
    session_node_id: str | None = None,
) -> str | None:
    normalized_phone = normalize_phone(phone)
    conversation = db.execute(
        select(Conversation)
        .where(Conversation.tenant_id == tenant_id, Conversation.phone_number == normalized_phone)
        .order_by(desc(Conversation.updated_at), desc(Conversation.id))
    ).scalars().first()
    if not conversation:
        logger.info("Flow ignorado: conversa nao encontrada tenant_id=%s phone=%s", tenant_id, normalized_phone)
        return None

    _ensure_conversation_state(conversation=conversation, message_text=message_text)
    user_identifier = conversation.phone_number
    user_message_text = message_text or ""
    normalized_text = _normalize_text(user_message_text)
    session_service = FlowSessionService(db)

    if flow_id:
        flow = resolve_flow(db=db, tenant_id=conversation.tenant_id, flow_id=flow_id)
    else:
        flow = get_active_visual_flow(db=db, tenant_id=conversation.tenant_id)
    if not flow:
        return None

    start_trigger = is_flow_trigger(flow, normalized_text)

    state = session_service.get_runtime_session_state(
        tenant_id=conversation.tenant_id,
        phone=user_identifier,
        flow_id=flow.id,
    )
    runtime_session = state["session"]
    session_status = state["status"]
    session_exists = state["exists"]
    session_active = state["is_active"]
    session_finalized = state["is_finalized"]

    saved_current_node_id = _parse_uuid(getattr(runtime_session, "current_node_id", None))
    if saved_current_node_id is None and isinstance(getattr(runtime_session, "variables", None), dict):
        saved_current_node_id = _parse_uuid(runtime_session.variables.get("current_node_id"))

    session_flow_version_id = _parse_uuid(getattr(runtime_session, "flow_version_id", None)) if runtime_session else None
    runtime_graph = _get_current_flow_runtime(db=db, flow=flow, tenant_id=conversation.tenant_id, flow_version_id=session_flow_version_id)

    forced_node_id = _parse_uuid(force_node) if force_node else None
    if forced_node_id is not None:
        forced_graph_node = _get_node(db=db, node_id=forced_node_id, tenant_id=conversation.tenant_id, runtime_graph=runtime_graph)
        saved_current_node_id = forced_node_id
        if runtime_session and forced_graph_node is not None:
            runtime_session.current_node_id = session_service.safe_update_current_node(
                session=runtime_session,
                next_node_id=forced_node_id,
                reason="process_flow_engine_force_node",
                graph_context={"executed_node_id": str(forced_node_id)},
            )
            db.add(runtime_session)
        logger.info(
            "[FLOW CONTINUE USING_FORCE_NODE] force_node=%s node_found=%s node_type=%s",
            forced_node_id,
            forced_graph_node is not None,
            _node_type_slug(forced_graph_node) if forced_graph_node else None,
        )

    requested_session_node_id = _parse_uuid(session_node_id) if session_node_id else None
    if requested_session_node_id is not None:
        saved_current_node_id = requested_session_node_id
        logger.info("[FLOW CONTINUE USING_SESSION_NODE] session_node_id=%s", requested_session_node_id)

    logger.info(
        "[FLOW ENTRY STATE] session_exists=%s status=%s current_node_id=%s incoming_text=%s",
        session_exists,
        session_status or None,
        saved_current_node_id,
        user_message_text,
    )

    logger.info(
        "[FLOW ROUTING] session_exists=%s session_active=%s session_finalized=%s status=%s",
        session_exists,
        session_active,
        session_finalized,
        session_status or None,
    )

    runtime_node_ids = [
        str(node.get("id"))
        for node in (runtime_graph.get("nodes") if isinstance(runtime_graph, dict) else [])
        if isinstance(node, dict) and node.get("id") is not None
    ]
    logger.info("[RUNTIME GRAPH NODE IDS] flow_id=%s node_ids=%s", flow.id, runtime_node_ids)

    session_context = runtime_session.context if runtime_session and isinstance(getattr(runtime_session, "context", None), dict) else {}
    selected_row_id = str(session_context.get("selected_row_id") or session_context.get("last_interactive_list_reply_id") or "").strip()
    selected_title = str(session_context.get("selected_title") or session_context.get("last_interactive_list_reply_title") or "").strip()
    choice_node_id = _parse_uuid(session_context.get("choice_node_id"))
    waiting_choice = session_context.get("waiting_choice") is True
    if runtime_session and (waiting_choice or selected_row_id or selected_title):
        _log_choice_runtime_marker(
            "[CHOICE RESUME START]",
            session_id=getattr(runtime_session, "id", None),
            current_node_id=getattr(runtime_session, "current_node_id", None),
            choice_node_id=choice_node_id or getattr(runtime_session, "current_node_id", None),
            selected_row_id=selected_row_id,
            selected_title=selected_title,
            correlation_id=_runtime_correlation_id(session_context),
            reason=f"waiting_choice={waiting_choice} choice_node_id_present={bool(choice_node_id)} selected_row_id_present={bool(selected_row_id)}",
        )
    if not runtime_session and (selected_row_id or selected_title):
        _log_choice_runtime_marker(
            "[CHOICE RESUME SKIPPED]",
            selected_row_id=selected_row_id,
            selected_title=selected_title,
            reason="no_runtime_session",
        )
        _log_choice_runtime_marker("[CHOICE RESUME REASON]", selected_row_id=selected_row_id, selected_title=selected_title, reason="runtime_session_missing_before_choice_resolution")
    elif runtime_session:
        if not waiting_choice and (selected_row_id or selected_title):
            _log_choice_runtime_marker(
                "[CHOICE RESUME SKIPPED]",
                session_id=getattr(runtime_session, "id", None),
                current_node_id=getattr(runtime_session, "current_node_id", None),
                choice_node_id=choice_node_id or getattr(runtime_session, "current_node_id", None),
                selected_row_id=selected_row_id,
                selected_title=selected_title,
                correlation_id=_runtime_correlation_id(session_context),
                reason="session_context_waiting_choice_not_true",
            )
            _log_choice_runtime_marker(
                "[CHOICE RESUME REASON]",
                session_id=getattr(runtime_session, "id", None),
                current_node_id=getattr(runtime_session, "current_node_id", None),
                choice_node_id=choice_node_id or getattr(runtime_session, "current_node_id", None),
                selected_row_id=selected_row_id,
                selected_title=selected_title,
                correlation_id=_runtime_correlation_id(session_context),
                reason=f"waiting_choice={session_context.get('waiting_choice')} context_keys={sorted(session_context.keys())}",
            )
        elif not choice_node_id and waiting_choice:
            _log_choice_runtime_marker(
                "[CHOICE RESUME SKIPPED]",
                session_id=getattr(runtime_session, "id", None),
                current_node_id=getattr(runtime_session, "current_node_id", None),
                selected_row_id=selected_row_id,
                selected_title=selected_title,
                correlation_id=_runtime_correlation_id(session_context),
                reason="missing_choice_node_id",
            )
            _log_choice_runtime_marker(
                "[CHOICE RESUME REASON]",
                session_id=getattr(runtime_session, "id", None),
                current_node_id=getattr(runtime_session, "current_node_id", None),
                selected_row_id=selected_row_id,
                selected_title=selected_title,
                correlation_id=_runtime_correlation_id(session_context),
                reason=f"context_keys={sorted(session_context.keys())}",
            )
        elif choice_node_id and selected_row_id and waiting_choice:
            choice_node = _get_node(db=db, node_id=choice_node_id, tenant_id=conversation.tenant_id, runtime_graph=runtime_graph)
            choice_node_type = _node_type_slug(choice_node) if choice_node else ""
            if choice_node_type != "choice":
                _log_choice_runtime_marker(
                    "[CHOICE RESUME SKIPPED]",
                    session_id=getattr(runtime_session, "id", None),
                    current_node_id=getattr(runtime_session, "current_node_id", None),
                    choice_node_id=choice_node_id,
                    selected_row_id=selected_row_id,
                    selected_title=selected_title,
                    correlation_id=_runtime_correlation_id(session_context),
                    reason=f"choice_node_type={choice_node_type or 'missing'}",
                )
                _log_choice_runtime_marker(
                    "[CHOICE RESUME REASON]",
                    session_id=getattr(runtime_session, "id", None),
                    current_node_id=getattr(runtime_session, "current_node_id", None),
                    choice_node_id=choice_node_id,
                    selected_row_id=selected_row_id,
                    selected_title=selected_title,
                    correlation_id=_runtime_correlation_id(session_context),
                    reason="stored_choice_node_not_choice_or_not_found",
                )
            else:
                choice_edges = _get_edges(db=db, flow_id=flow.id, source=choice_node_id, runtime_graph=runtime_graph)
                choice_options = _choice_options_from_node(_extract_node_data(choice_node), choice_edges)
                selected_option = _resolve_choice_option(selected_row_id, choice_options) or (
                    _resolve_choice_option(selected_title, choice_options) if selected_title else None
                )
                if selected_option:
                    saved_current_node_id = choice_node_id
                    selected_edge = _find_edge_for_handle(choice_edges, str(selected_option.get("handleId") or selected_option.get("id") or selected_row_id))
                    selected_target_node_id = _edge_target(selected_edge) if selected_edge else None
                    if isinstance(runtime_session.context, dict):
                        runtime_session.context = {
                            **runtime_session.context,
                            "selected_choice_target_node_id": str(selected_target_node_id) if selected_target_node_id else None,
                        }
                        db.add(runtime_session)
                    _log_choice_runtime_marker(
                        "[CHOICE LIST RESPONSE]",
                        session_id=getattr(runtime_session, "id", None),
                        current_node_id=getattr(runtime_session, "current_node_id", None),
                        choice_node_id=choice_node_id,
                        selected_row_id=selected_row_id,
                        selected_title=selected_title,
                        target_node_id=selected_target_node_id,
                        correlation_id=_runtime_correlation_id(session_context),
                    )
                    _log_choice_runtime_marker(
                        "[CHOICE OPTION RESOLVED]",
                        session_id=getattr(runtime_session, "id", None),
                        current_node_id=choice_node_id,
                        choice_node_id=choice_node_id,
                        selected_row_id=selected_row_id,
                        selected_title=selected_title,
                        target_node_id=selected_target_node_id,
                        correlation_id=_runtime_correlation_id(session_context),
                    )
                    logger.info(
                        "[FLOW CONTINUE USING_CHOICE_REPLY] session_id=%s choice_node_id=%s selected_row_id=%s selected_title=%s",
                        getattr(runtime_session, "id", None),
                        choice_node_id,
                        selected_row_id,
                        selected_title,
                    )
                else:
                    _log_choice_runtime_marker(
                        "[CHOICE RESUME SKIPPED]",
                        session_id=getattr(runtime_session, "id", None),
                        current_node_id=getattr(runtime_session, "current_node_id", None),
                        choice_node_id=choice_node_id,
                        selected_row_id=selected_row_id,
                        selected_title=selected_title,
                        correlation_id=_runtime_correlation_id(session_context),
                        reason="selected_option_not_resolved",
                    )
                    _log_choice_runtime_marker(
                        "[CHOICE RESUME REASON]",
                        session_id=getattr(runtime_session, "id", None),
                        current_node_id=getattr(runtime_session, "current_node_id", None),
                        choice_node_id=choice_node_id,
                        selected_row_id=selected_row_id,
                        selected_title=selected_title,
                        correlation_id=_runtime_correlation_id(session_context),
                        reason=f"options_count={len(choice_options)} option_ids={[str(option.get('id') or option.get('handleId') or '') for option in choice_options]}",
                    )

    current_graph_node = None
    current_node_type = ""
    current_node_raw_type = None
    if saved_current_node_id is not None:
        current_graph_node = _get_node(db=db, node_id=saved_current_node_id, tenant_id=conversation.tenant_id, runtime_graph=runtime_graph)
        if not current_graph_node:
            logger.error(
                "[FLOW SESSION_NODE_NOT_FOUND_IN_GRAPH] session_node_id=%s graph_node_ids=%s runtime_graph_source=%s session_flow_version_id=%s published_version_id=%s",
                saved_current_node_id,
                runtime_node_ids,
                runtime_graph.get("source"),
                getattr(runtime_session, "flow_version_id", None),
                runtime_graph.get("flow_version_id"),
            )
            return None
        current_node_raw_type = _node_get(current_graph_node, "type")
        current_node_type = _node_type_slug(current_graph_node)
        logger.info("[FLOW SESSION NODE FOUND] node_type=%s raw_node_type=%s", current_node_type, current_node_raw_type)

    session_context_for_routing = runtime_session.context if runtime_session and isinstance(getattr(runtime_session, "context", None), dict) else {}
    is_pending_choice_reply = bool(
        session_context_for_routing.get("waiting_choice") is True
        and (session_context_for_routing.get("selected_row_id") or session_context_for_routing.get("last_interactive_list_reply_id"))
    )
    saved_current_node_present = saved_current_node_id is not None
    start_trigger_match = bool(start_trigger)

    # Proteção 1: sessão aguardando resposta de choice com selected_row_id
    if is_pending_choice_reply and start_trigger_match:
        _log_choice_runtime_marker(
            "[FLOW RESTART DETECTED]",
            session_id=getattr(runtime_session, "id", None),
            current_node_id=saved_current_node_id,
            choice_node_id=session_context_for_routing.get("choice_node_id") or saved_current_node_id,
            selected_row_id=session_context_for_routing.get("selected_row_id") or session_context_for_routing.get("last_interactive_list_reply_id"),
            target_node_id=session_context_for_routing.get("selected_choice_target_node_id"),
            correlation_id=_runtime_correlation_id(session_context_for_routing),
        )
        logger.warning(
            "[FLOW RESTART DETECTED DETAIL] reason=choice_reply_matched_start_trigger trigger=%s session_id=%s current_node_id=%s",
            normalized_text,
            getattr(runtime_session, "id", None),
            saved_current_node_id,
        )
        start_trigger_match = False

    # Proteção 2 (NOVA): sessão ativa com current_node sendo um choice node
    # impede que texto livre (ex: "Oi") destrua a sessão em espera
    elif (
        start_trigger_match
        and session_active
        and saved_current_node_present
        and current_node_type == "choice"
    ):
        logger.warning(
            "[FLOW RESTART BLOCKED_CHOICE_WAITING] reason=active_choice_node_prevents_restart "
            "trigger=%s session_id=%s current_node_id=%s current_node_type=%s",
            normalized_text,
            getattr(runtime_session, "id", None),
            saved_current_node_id,
            current_node_type,
        )
        start_trigger_match = False
    session_running_with_current_node = bool(
        runtime_session
        and session_status in {"running", "active"}
        and saved_current_node_present
    )
    current_node_is_condition = current_node_type == "condition"
    condition_wait_state = session_running_with_current_node and current_node_is_condition
    effective_session_finalized = session_finalized and not session_running_with_current_node

    explicit_start_trigger = start_trigger_match
    if effective_session_finalized and not explicit_start_trigger:
        logger.info(
            "[ENGINE FINALIZED HARD BLOCK] session_id=%s status=%s incoming_text=%s",
            getattr(runtime_session, "id", None),
            session_status,
            user_message_text,
        )
        return None
    if effective_session_finalized and explicit_start_trigger:
        logger.info(
            "[FLOW EXPLICIT RESTART] trigger=%s old_session_id=%s",
            normalized_text,
            getattr(runtime_session, "id", None),
        )

    active_continue_term = (session_active or forced_node_id is not None) and saved_current_node_present and not start_trigger_match
    should_continue = active_continue_term or condition_wait_state
    should_restart = effective_session_finalized and start_trigger_match
    start_path_selected = not should_continue

    if condition_wait_state and (not session_active or start_trigger_match):
        logger.info(
            "[FLOW CONDITION CONTINUE PRESERVED] session_id=%s current_node_id=%s session_active=%s start_trigger=%s",
            getattr(runtime_session, "id", None),
            saved_current_node_id,
            session_active,
            start_trigger_match,
        )
    if should_continue:
        logger.info(
            "[FLOW ACTIVE CONTINUE] session_id=%s current_node_id=%s",
            getattr(runtime_session, "id", None),
            saved_current_node_id,
        )
    elif should_restart:
        logger.info("[FLOW RESTART PATH] trigger=%s", normalized_text)

    path = "START" if start_path_selected else "CONTINUE"

    published_version_id = _parse_uuid(getattr(flow, "published_version_id", None))
    if path == "CONTINUE":
        logger.info("[FLOW CONTINUE PATH]")
        if runtime_session and published_version_id and _parse_uuid(getattr(runtime_session, "flow_version_id", None)) != published_version_id:
            runtime_session.flow_version_id = published_version_id
            db.add(runtime_session)
            logger.info("[FLOW VERSION UPDATED_PRESERVING_NODE]")

        run_until_wait_node(
            db=db,
            flow=flow,
            runtime_graph=runtime_graph,
            session=conversation,
            start_node_id=saved_current_node_id,
            incoming_text=user_message_text,
        )
        conversation.mode = "flow"
        conversation.current_flow = flow.id
        if runtime_session is not None:
            runtime_status = str(getattr(runtime_session, "status", "") or "").strip().lower()
            if runtime_status not in RUNTIME_SESSION_FINAL_STATUSES and getattr(runtime_session, "current_node_id", None) is not None:
                runtime_session.status = "running"
            db.add(runtime_session)
        db.add(conversation)
        db.commit()
        return None

    logger.info("[FLOW START PATH]")
    if runtime_session is not None:
        _log_choice_runtime_marker(
            "[FLOW RESTART DETECTED]",
            session_id=getattr(runtime_session, "id", None),
            current_node_id=saved_current_node_id,
            choice_node_id=session_context_for_routing.get("choice_node_id") or saved_current_node_id,
            selected_row_id=session_context_for_routing.get("selected_row_id") or session_context_for_routing.get("last_interactive_list_reply_id"),
            target_node_id=session_context_for_routing.get("selected_choice_target_node_id"),
            correlation_id=_runtime_correlation_id(session_context_for_routing),
        )
        abandon_reason = "start_path_existing_runtime_session"
        runtime_current_node_id = getattr(runtime_session, "current_node_id", None)
        runtime_variables = getattr(runtime_session, "variables", None)
        runtime_variable_current_node_id = (
            runtime_variables.get("current_node_id")
            if isinstance(runtime_variables, dict)
            else None
        )
        runtime_status = ((getattr(runtime_session, "status", "") or "").strip().lower())
        abandon_condition = (
            f"start_path_selected={start_path_selected} "
            f"start_path_expression=not_should_continue "
            f"should_continue={should_continue} "
            f"should_continue_expression=(active_continue_term or condition_wait_state) "
            f"active_continue_term={active_continue_term} "
            f"active_continue_expression=(session_active and saved_current_node_present and not_start_trigger_match) "
            f"condition_wait_state={condition_wait_state} "
            f"condition_wait_expression=(session_running_with_current_node and current_node_is_condition) "
            f"session_active={session_active} "
            f"saved_current_node_present={saved_current_node_present} "
            f"start_trigger_match={start_trigger_match} "
            f"not_start_trigger_match={not start_trigger_match} "
            f"session_running_with_current_node={session_running_with_current_node} "
            f"current_node_is_condition={current_node_is_condition} "
            f"session_finalized={session_finalized} "
            f"effective_session_finalized={effective_session_finalized} "
            f"runtime_session_status={runtime_status or None} "
            f"runtime_session_current_node_id={runtime_current_node_id} "
            f"runtime_variable_current_node_id={runtime_variable_current_node_id} "
            f"saved_current_node_id={saved_current_node_id} "
            f"current_node_type={current_node_type or None} "
            f"current_node_raw_type={current_node_raw_type}"
        )
        logger.warning(
            "[ABANDON DECISION] session_id=%s current_node_id=%s flow_id=%s message_text=%s reason=%s condition=%s code_path=%s",
            getattr(runtime_session, "id", None),
            saved_current_node_id,
            getattr(flow, "id", None),
            user_message_text,
            abandon_reason,
            abandon_condition,
            "process_flow_engine:START:end_existing_runtime_session",
        )
        logger.warning(
            "[ABANDON GUARD TRACE] session_id=%s flow_id=%s requested_status=%s "
            "start_path_selected=%s start_path_expression=%s should_continue=%s should_continue_expression=%s "
            "active_continue_term=%s active_continue_expression=%s condition_wait_state=%s condition_wait_expression=%s "
            "session_active=%s saved_current_node_present=%s start_trigger_match=%s not_start_trigger_match=%s "
            "session_running_with_current_node=%s current_node_is_condition=%s session_finalized=%s effective_session_finalized=%s "
            "runtime_session.status=%s runtime_session.current_node_id=%s runtime_session.variables.current_node_id=%s "
            "saved_current_node_id=%s current_node.type=%s current_node.raw_type=%s code_path=%s",
            getattr(runtime_session, "id", None),
            getattr(flow, "id", None),
            "abandoned",
            start_path_selected,
            "not should_continue",
            should_continue,
            "(session_active and saved_current_node_present and not start_trigger_match) or condition_wait_state",
            active_continue_term,
            "session_active and saved_current_node_present and not start_trigger_match",
            condition_wait_state,
            "session_running_with_current_node and current_node_is_condition",
            session_active,
            saved_current_node_present,
            start_trigger_match,
            not start_trigger_match,
            session_running_with_current_node,
            current_node_is_condition,
            session_finalized,
            effective_session_finalized,
            runtime_status or None,
            runtime_current_node_id,
            runtime_variable_current_node_id,
            saved_current_node_id,
            current_node_type or None,
            current_node_raw_type,
            "process_flow_engine:START:end_existing_runtime_session",
        )
        session_service.end_session(runtime_session, status="abandoned")

    start_node = _get_start_node(
        db=db,
        flow_id=flow.id,
        tenant_id=conversation.tenant_id,
        runtime_graph=runtime_graph,
    )
    if not start_node:
        return None

    conversation.mode = "flow"
    conversation.current_flow = flow.id
    start_node_id = _parse_uuid(_node_get(start_node, "id"))
    conversation.current_node_id = None

    next_node_id: uuid.UUID | None = None
    if start_node_id is not None:
        outgoing_edges = _get_edges(db=db, flow_id=flow.id, source=start_node_id, runtime_graph=runtime_graph)
        if outgoing_edges:
            candidate_next_node_id = _parse_uuid(_edge_target(outgoing_edges[0]))
            candidate_next_node = (
                _get_node(db=db, node_id=candidate_next_node_id, tenant_id=conversation.tenant_id, runtime_graph=runtime_graph)
                if candidate_next_node_id
                else None
            )
            if candidate_next_node is not None:
                next_node_id = candidate_next_node_id
                candidate_next_type = (
                    candidate_next_node.get("type")
                    if isinstance(candidate_next_node, dict)
                    else getattr(candidate_next_node, "type", None)
                )
                logger.info(
                    "[START NEXT NODE RESOLVED] start_node_id=%s next_node_id=%s next_node_type=%s",
                    start_node_id,
                    next_node_id,
                    candidate_next_type,
                )

        if next_node_id is None:
            logger.warning(
                "[START NEXT NODE NOT FOUND] start_node_id=%s edges_count=%s edges_raw=%s",
                start_node_id,
                len(outgoing_edges),
                [
                    {
                        "source": str(_edge_source(edge)),
                        "target": str(_edge_target(edge)),
                        "source_handle": _edge_source_handle(edge),
                    }
                    for edge in outgoing_edges
                ],
            )

    run_until_wait_node(
        db=db,
        flow=flow,
        runtime_graph=runtime_graph,
        session=conversation,
        start_node_id=start_node_id,
        incoming_text=None,
    )
    saved_wait_node_id = _parse_uuid(getattr(conversation, "current_node_id", None)) or next_node_id
    runtime_session = session_service.save_runtime_session(
        tenant_id=conversation.tenant_id,
        user_identifier=user_identifier,
        flow=flow,
        current_node_id=saved_wait_node_id,
        context=conversation.context if isinstance(conversation.context, dict) else {},
        status="running",
        variables={"current_node_id": str(saved_wait_node_id) if saved_wait_node_id else None},
        executed_node_id=start_node_id,
        next_node_id=saved_wait_node_id,
    )
    logger.info("[FLOW START SAVED_WAIT_NODE] current_node_id=%s", saved_wait_node_id)
    db.add(conversation)
    db.add(runtime_session)
    db.commit()
    return None

def seed_default_visual_flow(db: Session, flow: Flow, tenant_id: uuid.UUID) -> None:
    existing_start = db.execute(
        select(FlowNode.id).where(FlowNode.flow_id == flow.id).limit(1)
    ).scalar_one_or_none()
    if existing_start:
        return

    start = FlowNode(
        flow_id=flow.id,
        tenant_id=tenant_id,
        type="choice",
        content="Voce quer vendas, suporte ou atendimento?",
        metadata_json={
            "isStart": True,
            "label": "inicio",
            "buttons": [
                {"label": "vendas"},
                {"label": "suporte"},
                {"label": "atendimento"},
            ],
        },
        position_x=120,
        position_y=120,
    )
    vendas = FlowNode(
        flow_id=flow.id,
        tenant_id=tenant_id,
        type="message",
        content="Perfeito, vamos seguir por vendas",
        metadata_json={"label": "vendas"},
        position_x=420,
        position_y=20,
    )
    suporte = FlowNode(
        flow_id=flow.id,
        tenant_id=tenant_id,
        type="message",
        content="Perfeito, vamos seguir por suporte",
        metadata_json={"label": "suporte"},
        position_x=420,
        position_y=140,
    )
    atendimento = FlowNode(
        flow_id=flow.id,
        tenant_id=tenant_id,
        type="message",
        content="Perfeito, vamos seguir por atendimento",
        metadata_json={"label": "atendimento"},
        position_x=420,
        position_y=260,
    )

    db.add_all([start, vendas, suporte, atendimento])
    db.flush()

    db.add_all(
        [
            FlowEdge(flow_id=flow.id, source=start.id, target=vendas.id, condition="vendas"),
            FlowEdge(flow_id=flow.id, source=start.id, target=suporte.id, condition="suporte"),
            FlowEdge(flow_id=flow.id, source=start.id, target=atendimento.id, condition="atendimento"),
        ]
    )
    db.flush()


def get_flow_graph(db: Session, tenant_id: uuid.UUID, flow_id: str) -> dict[str, Any]:
    flow = resolve_flow(db=db, tenant_id=tenant_id, flow_id=flow_id)
    selected_version = flow.current_version
    if not selected_version and flow.current_version_id:
        selected_version = db.execute(
            select(FlowVersion).where(FlowVersion.id == flow.current_version_id, FlowVersion.flow_id == flow.id)
        ).scalars().first()
    nodes, edges = flow_version_nodes_edges(selected_version)
    if not nodes:
        nodes = flow.nodes_json if isinstance(flow.nodes_json, list) else flow.nodes if isinstance(flow.nodes, list) else []
        edges = flow.edges_json if isinstance(flow.edges_json, list) else flow.edges if isinstance(flow.edges, list) else []
    return {
        "flow_id": str(flow.id),
        "version_id": str(selected_version.id) if selected_version else None,
        "source": "builder_version" if selected_version else "builder_draft",
        "nodes": nodes if isinstance(nodes, list) else [],
        "edges": edges if isinstance(edges, list) else [],
    }

def save_flow_graph(db: Session, tenant_id: uuid.UUID, flow_id: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, str]:
    flow = resolve_flow(db=db, tenant_id=tenant_id, flow_id=flow_id)
    nodes_payload = nodes or []
    edges_payload = edges or []
    print("[FLOW SAVE] nodes:", len(nodes_payload))
    valid, error = validate_flow_structure(nodes_payload, edges_payload)
    logger.info(
        "[FLOW SAVE] flow_id=%s nodes_count=%s validation_status=%s",
        flow.id,
        len(nodes_payload),
        "valid" if valid else "invalid",
    )
    if not valid:
        logger.error(
            "[FLOW ERROR] save_validation_failed flow_id=%s detail=%s nodes_count=%s edges_count=%s",
            flow.id,
            error,
            len(nodes_payload),
            len(edges_payload),
        )
        raise ValueError(error or "Flow inválido")

    node_id_map: dict[str, str] = {}
    normalized_nodes: list[dict[str, Any]] = []
    for item in nodes_payload:
        if not isinstance(item, dict):
            continue
        raw_id = str(item.get("id") or "").strip()
        normalized_id = raw_id
        try:
            normalized_id = str(uuid.UUID(raw_id))
        except (ValueError, TypeError):
            normalized_id = str(uuid.uuid4())
        node_id_map[raw_id or normalized_id] = normalized_id
        node_payload = dict(item)
        node_payload["id"] = normalized_id
        normalized_nodes.append(node_payload)

    normalized_edges: list[dict[str, Any]] = []
    for edge in edges_payload:
        if not isinstance(edge, dict):
            continue
        source_raw = str(edge.get("source") or "").strip()
        target_raw = str(edge.get("target") or "").strip()
        source = node_id_map.get(source_raw, source_raw)
        target = node_id_map.get(target_raw, target_raw)
        edge_payload = dict(edge)
        edge_payload["source"] = source
        edge_payload["target"] = target
        normalized_edges.append(edge_payload)

    logger.info(
        "[NORMALIZED FLOW GRAPH] flow_id=%s nodes_count=%s edges_count=%s",
        flow.id,
        len(normalized_nodes),
        len(normalized_edges),
    )

    last_version = db.query(func.max(FlowVersion.version)).filter(FlowVersion.flow_id == flow.id).scalar()
    next_version = (last_version or 0) + 1

    previous_active = db.execute(
        select(FlowVersion).where(FlowVersion.flow_id == flow.id, FlowVersion.is_active.is_(True))
    ).scalars().first()

    db.query(FlowVersion).filter(FlowVersion.flow_id == flow.id).update(
        {FlowVersion.is_active: False},
        synchronize_session=False,
    )

    flow_version = FlowVersion(
        flow_id=flow.id,
        tenant_id=tenant_id,
        version=next_version,
        is_active=True,
    )
    apply_flow_version_snapshot_metadata(flow_version, normalized_nodes, normalized_edges)
    db.add(flow_version)
    db.flush()
    flow.current_version_id = flow_version.id
    if flow.published_version_id is None:
        logger.warning("[PUBLISH BLOCKED RUNTIME] action=save_flow_graph_auto_publish flow_id=%s", flow.id)
    flow.version = next_version
    db.add(flow)
    if previous_active:
        logger.info(
            "[FLOW BACKUP PRESERVED] flow_id=%s previous_active_version_id=%s",
            flow.id,
            previous_active.id,
        )
    invalidate_flow_runtime_cache(flow.id)
    if flow.is_active:
        print("[FLOW ACTIVE]:", flow.id)
    logger.info(
        "[FLOW VERSION CREATED] flow_id=%s version_id=%s version=%s",
        flow.id,
        flow_version.id,
        flow_version.version,
    )

    db.query(FlowEdge).filter(FlowEdge.flow_id == flow.id).delete(synchronize_session=False)
    db.query(FlowNode).filter(FlowNode.flow_id == flow.id, FlowNode.tenant_id == tenant_id).delete(synchronize_session=False)
    db.flush()

    node_uuid_map: dict[str, uuid.UUID] = {}
    for item in normalized_nodes:
        raw_id = str(item.get("id") or "").strip()
        node_id = uuid.UUID(raw_id) if raw_id else uuid.uuid4()

        data = item.get("data") or {}
        position = item.get("position") or {}
        metadata = data.get("metadata") if isinstance(data, dict) else {}
        if not isinstance(metadata, dict):
            metadata = {}

        if isinstance(data, dict):
            if data.get("text") is not None:
                metadata["text"] = data.get("text")
            if data.get("label"):
                metadata["label"] = data.get("label")
            if isinstance(data.get("buttons"), list):
                metadata["buttons"] = data.get("buttons")
            if data.get("condition") is not None:
                metadata["condition"] = data.get("condition")
            if data.get("action") is not None:
                metadata["action"] = data.get("action")
            if data.get("isStart") is not None:
                metadata["isStart"] = bool(data.get("isStart"))

        node_type = item.get("type") or "default"

        node = FlowNode(
            id=node_id,
            flow_id=flow.id,
            tenant_id=tenant_id,
            type=node_type,
            content=(data.get("content") or data.get("text")) if isinstance(data, dict) else None,
            metadata_json=metadata,
            position_x=int(position.get("x", 0) or 0),
            position_y=int(position.get("y", 0) or 0),
        )
        db.add(node)
        node_uuid_map[raw_id or str(node_id)] = node_id

    db.flush()

    for item in normalized_edges:
        source_raw = str(item.get("source") or "").strip()
        target_raw = str(item.get("target") or "").strip()
        source_id = node_uuid_map.get(source_raw)
        target_id = node_uuid_map.get(target_raw)
        if not source_id or not target_id:
            continue

        data = item.get("data") or {}
        condition = (
            (data.get("condition") if isinstance(data, dict) else None)
            or (data.get("sourceHandle") if isinstance(data, dict) else None)
            or item.get("label")
            or item.get("sourceHandle")
        ) or None
        if condition == "":
            condition = None

        edge_id = uuid.uuid4()
        if item.get("id"):
            try:
                edge_id = uuid.UUID(str(item["id"]))
            except ValueError:
                edge_id = uuid.uuid4()

        db.add(
            FlowEdge(
                id=edge_id,
                flow_id=flow.id,
                source=source_id,
                target=target_id,
                condition=condition,
            )
        )

    db.flush()
    return {"flow_id": str(flow.id), "status": "saved"}


def resolve_flow(db: Session, tenant_id: uuid.UUID, flow_id: str) -> Flow:
    if flow_id == "default":
        return _get_or_create_visual_flow(db=db, tenant_id=tenant_id)

    parsed_flow_id = uuid.UUID(flow_id)
    flow = db.execute(select(Flow).where(Flow.id == parsed_flow_id, Flow.tenant_id == tenant_id)).scalars().first()
    if not flow:
        raise ValueError("Flow nao encontrado para este tenant")
    return flow
