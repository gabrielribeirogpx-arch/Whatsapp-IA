from __future__ import annotations

import unicodedata
import uuid
import logging
import time
import hashlib
import json
from datetime import datetime, timezone
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import Conversation, Flow, FlowEdge, FlowNode, FlowVersion, Tenant
from app.models.flow_session import FlowSession
from app.services.delay_queue_service import enqueue_delay
from app.services.cache_service import TTL_FLOW_SECONDS, cache_aside_json
from app.services.flow_analytics_service import record_flow_event
from app.services.queue import enqueue_send_message
from app.utils.phone import normalize_phone
from app.services.flow_session_service import FlowSessionService

DEFAULT_FLOW_NAME = "default_visual"
MAX_AUTO_STEPS = 10
MAX_RETRIES = 3
logger = logging.getLogger(__name__)
_FLOW_RUNTIME_CACHE: dict[uuid.UUID, dict[str, Any]] = {}
_FLOW_RUNTIME_EVENT_GUARD: set[str] = set()
STRONG_YES_MATCHES = {"sim", "s", "claro", "quero", "com certeza", "yes"}
STRONG_NO_MATCHES = {"nao", "n", "negativo", "no"}


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
        node_id = str((node or {}).get("id") or "").strip()
        if not node_id:
            add_issue(errors, "NODE_ID_REQUIRED", None, "Node sem id")
            continue
        node_map[node_id] = node
        outgoing[node_id] = 0
        incoming[node_id] = 0
        condition_handles[node_id] = set()
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        if bool(data.get("isStart")):
            start_nodes.append(node_id)

    if len(start_nodes) != 1:
        add_issue(errors, "SINGLE_START_REQUIRED", None, "Flow precisa ter exatamente 1 start node.")

    for edge in edges_payload:
        source = str((edge or {}).get("source") or "").strip()
        target = str((edge or {}).get("target") or "").strip()
        if source not in node_map or target not in node_map:
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
        valid, _ = validate_flow_legacy(
            version.nodes if isinstance(version.nodes, list) else [],
            version.edges if isinstance(version.edges, list) else [],
        )
        if valid:
            return version
    return None


def invalidate_flow_runtime_cache(flow_id: uuid.UUID) -> None:
    _FLOW_RUNTIME_CACHE.pop(flow_id, None)
    logger.info("[CACHE INVALIDATED] flow_id=%s", flow_id)


def _get_valid_flow_version_by_id(db: Session, flow: Flow, version_id: uuid.UUID | None) -> FlowVersion | None:
    if not version_id:
        return None
    selected = db.execute(
        select(FlowVersion).where(FlowVersion.id == version_id, FlowVersion.flow_id == flow.id)
    ).scalars().first()
    if not selected:
        return None
    valid, _ = validate_flow_structure(
        nodes=selected.nodes if isinstance(selected.nodes, list) else [],
        edges=selected.edges if isinstance(selected.edges, list) else [],
    )
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
    v = FlowVersion(flow_id=flow.id, tenant_id=flow.tenant_id, version=next_version, nodes=nodes, edges=edges, snapshot={"nodes": nodes, "edges": edges}, is_active=True, is_published=True)
    db.add(v)
    db.flush()
    flow.current_version_id = v.id
    flow.published_version_id = v.id
    flow.version = v.version
    db.add(flow)
    return v
def resolve_runtime_flow_graph(db: Session, tenant_id: uuid.UUID, flow_id: str) -> dict[str, Any]:
    flow = resolve_flow(db=db, tenant_id=tenant_id, flow_id=flow_id)
    cached = _FLOW_RUNTIME_CACHE.get(flow.id)
    if cached:
        cached_nodes = cached.get("nodes") if isinstance(cached, dict) else []
        logger.info(
            "[CACHE HIT] cache_key=%s cached_version_id=%s cached_start_text=%s",
            f"runtime_flow:{flow.id}",
            cached.get("version_id") if isinstance(cached, dict) else None,
            _start_preview_from_nodes(cached_nodes if isinstance(cached_nodes, list) else []),
        )
        return cached

    selected_version = None
    source = "none"
    if flow.published_version_id:
        selected_version = _get_valid_flow_version_by_id(db=db, flow=flow, version_id=flow.published_version_id)
        source = "published_version"
        if not selected_version:
            invalid_version = _get_flow_version_by_id(db=db, flow=flow, version_id=flow.published_version_id)
            invalid_nodes = invalid_version.nodes if invalid_version and isinstance(invalid_version.nodes, list) else []
            invalid_edges = invalid_version.edges if invalid_version and isinstance(invalid_version.edges, list) else []
            runtime_validation = validate_flow({"nodes": invalid_nodes, "edges": invalid_edges}, mode="published")
            validation_errors = runtime_validation.get("errors") if isinstance(runtime_validation, dict) else []
            if not isinstance(validation_errors, list):
                validation_errors = [validation_errors]
            start_node_id = None
            for node in invalid_nodes:
                if not isinstance(node, dict):
                    continue
                data = node.get("data") if isinstance(node.get("data"), dict) else {}
                if data.get("isStart"):
                    start_node_id = str(node.get("id") or "") or None
                    break

            should_raise_invalid_published = (
                invalid_version is None
                or len(invalid_nodes) == 0
                or not start_node_id
                or len(validation_errors) > 0
            )
            if should_raise_invalid_published:
                start_text_preview = _start_preview_from_nodes(invalid_nodes)
                logger.warning(
                    "[RUNTIME INVALID PUBLISHED VERSION] flow_id=%s version_id=%s nodes_count=%s edges_count=%s validation_errors=%s start_node_id=%s start_text_preview=%s",
                    flow.id,
                    str(flow.published_version_id),
                    len(invalid_nodes),
                    len(invalid_edges),
                    validation_errors,
                    start_node_id,
                    start_text_preview,
                )
                raise HTTPException(
                    status_code=409,
                    detail=f"Published version inválida para flow {flow.id}. Execute force-republish-current.",
                )

            selected_version = invalid_version
            logger.info(
                "[RUNTIME PUBLISHED VERSION OK] flow_id=%s version_id=%s nodes_count=%s edges_count=%s start_node_id=%s validation_errors=%s",
                flow.id,
                str(flow.published_version_id),
                len(invalid_nodes),
                len(invalid_edges),
                start_node_id,
                validation_errors,
            )
    else:
        selected_version = _get_valid_flow_version_by_id(db=db, flow=flow, version_id=flow.current_version_id)
        source = "current_version"

    if not selected_version:
        raise HTTPException(
            status_code=409,
            detail=f"Nenhuma versão executável encontrada para flow {flow.id}.",
        )

    nodes = selected_version.nodes if selected_version and isinstance(selected_version.nodes, list) else []
    edges = selected_version.edges if selected_version and isinstance(selected_version.edges, list) else []
    logger.info(
        "[RUNTIME VERSION] flow_id=%s source=%s version_id=%s version_number=%s",
        flow.id,
        source,
        getattr(selected_version, "id", None),
        getattr(selected_version, "version", None),
    )
    logger.info("[NODES COUNT] flow_id=%s runtime_nodes=%s runtime_edges=%s", flow.id, len(nodes), len(edges))
    mismatch = bool(selected_version and selected_version.flow_id != flow.id)
    if mismatch:
        logger.warning(
            "[FLOW VERSION MISMATCH] flow_id=%s selected_version_id=%s selected_flow_id=%s",
            flow.id,
            getattr(selected_version, "id", None),
            getattr(selected_version, "flow_id", None),
        )
        raise HTTPException(
            status_code=409,
            detail=f"[FLOW VERSION MISMATCH] flow_id={flow.id}. Execute force-republish-current.",
        )

    runtime_payload = {
        "flow_id": str(flow.id),
        "version_id": str(selected_version.id) if selected_version else None,
        "source": source,
        "nodes": nodes if isinstance(nodes, list) else [],
        "edges": edges if isinstance(edges, list) else [],
    }
    start_node_id = None
    for node in runtime_payload["nodes"]:
        if not isinstance(node, dict):
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        if bool(data.get("isStart")):
            start_node_id = str(node.get("id") or "") or None
            break
    start_text_preview = _start_preview_from_nodes(runtime_payload["nodes"])
    logger.info(
        "[RUNTIME GRAPH SOURCE] flow_id=%s version_id=%s version=%s source=%s start_node_id=%s start_text_preview=%s",
        flow.id,
        runtime_payload["version_id"],
        getattr(selected_version, "version", None),
        runtime_payload["source"],
        start_node_id,
        start_text_preview,
    )
    logger.info(
        "[FLOW_RUNTIME_SELECTED] flow_id=%s version_id=%s source=%s nodes=%s edges=%s",
        runtime_payload["flow_id"],
        runtime_payload["version_id"],
        runtime_payload["source"],
        len(runtime_payload["nodes"]),
        len(runtime_payload["edges"]),
    )
    logger.info(
        "[FLOW VERSION] flow_id=%s published_version_id=%s current_version_id=%s selected_version_id=%s source=%s",
        flow.id,
        flow.published_version_id,
        flow.current_version_id,
        runtime_payload["version_id"],
        runtime_payload["source"],
    )
    _FLOW_RUNTIME_CACHE[flow.id] = runtime_payload
    return runtime_payload


def _load_flow_version_runtime(flow: Flow, tenant_id: uuid.UUID, flow_version: FlowVersion) -> dict[str, Any]:
    raw_nodes = flow_version.nodes if isinstance(flow_version.nodes, list) else []
    raw_edges = flow_version.edges if isinstance(flow_version.edges, list) else []
    nodes: list[VersionedFlowNode] = []
    node_map: dict[uuid.UUID, VersionedFlowNode] = {}
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
        node_map[node_id] = node
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
        )
        edges.append(edge)
        edges_by_source.setdefault(source_id, []).append(edge)

    logger.info(
        "[FLOW VERSION LOADED] flow_id=%s version_id=%s version=%s",
        flow.id,
        flow_version.id,
        flow_version.version,
    )
    return {"nodes": nodes, "edges": edges, "node_map": node_map, "edges_by_source": edges_by_source}


def _empty_runtime_graph() -> dict[str, Any]:
    return {"nodes": [], "edges": [], "node_map": {}, "edges_by_source": {}}


def _get_current_flow_runtime(db: Session, flow: Flow, tenant_id: uuid.UUID) -> dict[str, Any]:
    resolved = resolve_runtime_flow_graph(db=db, tenant_id=tenant_id, flow_id=str(flow.id))
    if not resolved["nodes"]:
        return _empty_runtime_graph()
    runtime_version = FlowVersion(
        flow_id=flow.id,
        version=flow.version or 1,
        nodes=resolved["nodes"],
        edges=resolved["edges"],
    )
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
        )
        .order_by(Flow.priority.desc(), Flow.created_at.asc(), Flow.id.asc())
    ).scalars().all()
    for flow in candidates:
        runtime_graph = _get_current_flow_runtime(db=db, flow=flow, tenant_id=tenant_id)
        nodes = runtime_graph.get("nodes") if isinstance(runtime_graph, dict) else None
        start_node = _find_start_node(nodes or []) if isinstance(nodes, list) else None
        if start_node:
            return flow
    return None


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

    for node in nodes:
        node_data = getattr(node, "data", None)
        if not isinstance(node_data, dict):
            node_data = getattr(node, "metadata_json", None)
        if node_data and node_data.get("isStart") is True:
            return node
    return None


def _find_start_node(nodes: list[Any]) -> Any | None:
    def _extract_node_fields(node: Any) -> tuple[str, Any, str | None, Any]:
        source = "dict" if isinstance(node, dict) else "orm"
        if isinstance(node, dict):
            data = node.get("data") or {}
            node_id = node.get("id")
            node_type = node.get("type")
            position = node.get("position")
        else:
            data = getattr(node, "data", None) or getattr(node, "data_json", None) or {}
            node_id = getattr(node, "id", None)
            node_type = getattr(node, "type", None)
            position = getattr(node, "position", None)

        if isinstance(data, str):
            try:
                data = json.loads(data)
            except (TypeError, ValueError):
                data = {}
        if not isinstance(data, dict):
            data = {}

        return source, node_id, node_type, position, data

    sortable_nodes: list[tuple[Any, Any, Any]] = []

    # 1. prioridade: flag isStart no data
    for node in nodes:
        source, node_id, node_type, position, data = _extract_node_fields(node)
        is_start = data.get("isStart") is True
        logger.info(
            "[FLOW START NODE] source=%s node_id=%s is_start=%s",
            source,
            node_id,
            is_start,
        )
        sortable_nodes.append((node, position, node_id))
        if is_start:
            logger.info(
                "[FLOW START NODE] selected node_id=%s reason=isStart",
                node_id,
            )
            return node

    # 2. fallback por tipo
    for node in nodes:
        _, node_id, node_type, _, _ = _extract_node_fields(node)
        if isinstance(node_type, str) and node_type.lower() in {"start", "trigger", "inicio"}:
            logger.info(
                "[FLOW START NODE] selected node_id=%s reason=node_type",
                node_id,
            )
            return node

    # 3. fallback por ordenação (position/id)
    if sortable_nodes:
        selected, _, selected_id = sorted(
            sortable_nodes,
            key=lambda item: (
                item[1] is None,
                str(item[1]) if item[1] is not None else "",
                item[2] is None,
                str(item[2]) if item[2] is not None else "",
            ),
        )[0]
        logger.info(
            "[FLOW START NODE] selected node_id=%s reason=position_or_id",
            selected_id,
        )
        return selected

    logger.info("[FLOW START NODE] selected node_id=None reason=empty_nodes")
    return None




def _node_get(node: Any, key: str, default: Any = None) -> Any:
    if isinstance(node, dict):
        return node.get(key, default)
    return getattr(node, key, default)


def _get_start_node(
    db: Session,
    flow_id: uuid.UUID,
    tenant_id: uuid.UUID,
    runtime_graph: dict[str, Any] | None = None,
) -> FlowNode | VersionedFlowNode | None:
    if runtime_graph:
        nodes = runtime_graph.get("nodes", [])
    else:
        nodes = db.execute(
            select(FlowNode)
            .where(FlowNode.flow_id == flow_id, FlowNode.tenant_id == tenant_id)
            .order_by(FlowNode.created_at.asc(), FlowNode.id.asc())
        ).scalars().all()

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

    start_node = find_start_node({"nodes": nodes})
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
        nodes = db.execute(
            select(FlowNode)
            .where(FlowNode.flow_id == flow_id, FlowNode.tenant_id == conversation.tenant_id)
            .order_by(FlowNode.created_at.asc(), FlowNode.id.asc())
        ).scalars().all()

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
        start_node = _find_start_node(node_payload)
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
        return runtime_graph.get("node_map", {}).get(node_id)
    return db.execute(
        select(FlowNode).where(FlowNode.id == node_id, FlowNode.tenant_id == tenant_id)
    ).scalars().first()


def _get_edges(
    db: Session,
    flow_id: uuid.UUID,
    source: uuid.UUID,
    runtime_graph: dict[str, Any] | None = None,
) -> list[FlowEdge | VersionedFlowEdge]:
    if runtime_graph:
        return runtime_graph.get("edges_by_source", {}).get(source, [])
    return db.execute(
        select(FlowEdge)
        .where(FlowEdge.flow_id == flow_id, FlowEdge.source == source)
        .order_by(FlowEdge.id.asc())
    ).scalars().all()


def _pick_default_edge(edges: list[FlowEdge | VersionedFlowEdge]) -> FlowEdge | VersionedFlowEdge | None:
    for edge in edges:
        condition = _normalize_text(edge.condition)
        if condition in {"", "default", "else", "next"}:
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
        event_type="message_received",
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
    if node_type.endswith("node"):
        node_type = node_type[:-4]
    _emit_runtime_event(
        db=db,
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        flow_id=flow_id,
        flow_version_id=flow_version_id,
        node_id=node.id,
        event_type="node_entered",
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
    if node_type.endswith("node"):
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


def _render_choice_prompt(node_data: dict[str, Any], edges: list[FlowEdge | VersionedFlowEdge]) -> str:
    base = (node_data.get("content") or "Escolha uma opcao:").strip()
    raw_buttons = node_data.get("buttons") if isinstance(node_data.get("buttons"), list) else []
    button_labels = [str(button.get("label")).strip() for button in raw_buttons if isinstance(button, dict) and button.get("label")]

    if button_labels:
        return f"{base}\n\n" + "\n".join(f"- {label}" for label in button_labels)

    conditions = [edge.condition.strip() for edge in edges if edge.condition and edge.condition.strip()]
    if conditions:
        return f"{base}\n\n" + "\n".join(f"- {label}" for label in conditions)

    return base


def _send_flow_whatsapp_message(tenant: Tenant, phone: str, text: str) -> str | None:
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
    try:
        job_id = enqueue_send_message({"tenant_id": tenant.id, "phone": phone, "text": content})
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
) -> str | None:
    content = (text or "").strip()
    if not content or not phone:
        return None

    has_buttons = bool(buttons)
    message_kind = "buttons" if has_buttons else "text"
    hash_source = (template_or_node_text or content).strip()
    text_hash = hashlib.sha256(hash_source.encode("utf-8")).hexdigest()[:16] if hash_source else None

    payload: dict[str, Any] = {"tenant_id": tenant_id, "phone": phone, "text": content}
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
            event_type="message_queued",
            metadata={
                "channel": channel,
                "message_kind": message_kind,
                "has_buttons": has_buttons,
                "template_or_node_text_hash": text_hash,
            },
            dedupe_bucket_seconds=1,
        )
    return job_id


def _send_flow_interactive_buttons(tenant: Tenant, phone: str, text: str, buttons: list[dict]) -> None:
    """Enfileira envio de botoes; worker aplica fallback para texto simples se falhar."""
    print(f"[FLOW BUTTON SEND] Tentando enviar botoes: {[b.get('label') for b in buttons]}")
    try:
        job_id = enqueue_send_message({"tenant_id": tenant.id, "phone": phone, "text": text, "buttons": buttons})
        print(f"[FLOW BUTTON SEND RESULT] job_id={job_id}")
    except Exception as error:
        print(f"[FLOW BUTTON ERROR] {error} — usando fallback texto em fila")
        _send_flow_whatsapp_message(tenant=tenant, phone=phone, text=text)


def _text_preview(value: str | None, limit: int = 120) -> str:
    if not value:
        return ""
    text = " ".join(str(value).split())
    return text[:limit]




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
) -> FlowSession | None:
    node_data = _extract_node_data(start_node)
    node_type = str(_node_get(start_node, "type") or "").strip().lower()
    if node_type.endswith("node"):
        node_type = node_type[:-4]

    next_node_id: uuid.UUID | None = None
    start_node_id = _node_get(start_node, "id")
    logger.info("[FLOW START MESSAGE ATTEMPT] node_id=%s node_type=%s", start_node_id, node_type)

    if node_type == "message":
        text = _resolve_node_text(node_data)
        job_id = _send_flow_whatsapp_message(tenant=tenant, phone=conversation.phone_number, text=text)
        if not job_id:
            logger.error("[FLOW START MESSAGE NOT SENT] node_id=%s", start_node_id)
            next_node_id = start_node_id
            _safe_set_conversation_current_node(db, conversation, next_node_id)
            return session_service.save_runtime_session(
                tenant_id=conversation.tenant_id,
                user_identifier=user_identifier,
                flow=flow,
                current_node_id=next_node_id,
                context=conversation.context if isinstance(conversation.context, dict) else {},
                status="running",
                variables={"flow_version": published_version_number},
            )
        logger.info(
            "[FLOW START MESSAGE SENT] node_id=%s text_preview=%s",
            start_node_id,
            _text_preview(text),
        )

    start_edges = _get_edges(
        db=db,
        flow_id=flow.id,
        source=start_node_id,
        runtime_graph=runtime_graph,
    )
    next_edge = _pick_default_edge(start_edges)
    if next_edge:
        next_node_id = next_edge.target
    elif node_type != "terminal":
        next_node_id = start_node_id

    _safe_set_conversation_current_node(db, conversation, next_node_id)
    runtime_session = session_service.save_runtime_session(
        tenant_id=conversation.tenant_id,
        user_identifier=user_identifier,
        flow=flow,
        current_node_id=next_node_id,
        context=conversation.context if isinstance(conversation.context, dict) else {},
        status="running",
        variables={"flow_version": published_version_number},
    )
    return runtime_session
def process_flow_engine(
    db: Session,
    tenant_id: uuid.UUID,
    phone: str,
    message_text: str = "",
    force_node: uuid.UUID | None = None,
    flow_id: str | None = None,
) -> str | None:
    """
    Semântica de runtime/sessão:
    - abandoned: sessão expirada por TTL, reset manual, fallback_limit_exceeded ou fallback para bot.
    - abandon_reason: persistido em flow_sessions.abandon_reason e também enviado no metadata dos eventos.
    - conversion: emitido apenas uma vez por sessão quando trigger mínimo é satisfeito
      (node action com metadata conversion=true ou node id listado em flow.settings.conversion_node_ids).
    - flow_completed: emitido ao atingir node terminal do grafo.
    - ended_at: obrigatório para encerramentos finais (completed/abandoned/conversion final) via end_session.
    """
    normalized_phone = normalize_phone(phone)
    conversation = db.execute(
        select(Conversation)
        .where(Conversation.tenant_id == tenant_id, Conversation.phone_number == normalized_phone)
        .order_by(desc(Conversation.updated_at), desc(Conversation.id))
    ).scalars().first()
    if not conversation:
        logger.info("Flow ignorado: conversa nao encontrada tenant_id=%s phone=%s", tenant_id, normalized_phone)
        return None

    had_active_session = conversation.current_node_id is not None
    _ensure_conversation_state(conversation=conversation, message_text=message_text)
    if should_reset_context(message=message_text or "", context=conversation.context):
        conversation.context = {}
        logger.info("[CONTEXT RESET]")
    if flow_id:
        try:
            flow = resolve_flow(db=db, tenant_id=conversation.tenant_id, flow_id=flow_id)
        except Exception:
            logger.exception("[FLOW SELECT ERROR] tenant_id=%s flow_id=%s", conversation.tenant_id, flow_id)
            return None
    else:
        flow = get_active_visual_flow(db=db, tenant_id=conversation.tenant_id)
        if not flow:
            logger.info("[FLOW ROUTING] active_flow_found=false tenant_id=%s", conversation.tenant_id)
            return None
        logger.info("[FLOW ROUTING] active_flow_found=true flow_id=%s", flow.id)
    logger.info("[FLOW SELECTED] %s", flow_id or str(flow.id))
    runtime_graph = _get_current_flow_runtime(db=db, flow=flow, tenant_id=conversation.tenant_id)
    current_flow_version_id = _parse_uuid(runtime_graph.get("version_id") if isinstance(runtime_graph, dict) else None)
    if current_flow_version_id is None:
        current_flow_version_id = _parse_uuid(
            getattr(flow, "published_version_id", None)
            or getattr(flow, "current_version_id", None)
        )
    session_service = FlowSessionService(db)
    user_identifier = conversation.phone_number
    normalized_message = _normalize_text(message_text)
    runtime_session, invalid_reason = session_service.get_runtime_session(conversation.tenant_id, user_identifier, flow)
    session_version = None
    if runtime_session and isinstance(runtime_session.variables, dict):
        session_version = runtime_session.variables.get("flow_version")
    published_version = getattr(flow, "published_version", None)
    published_version_number = getattr(published_version, "version", None) if published_version else None
    current_version_number = getattr(getattr(flow, "current_version", None), "version", None)
    logger.info(
        "[FLOW SESSION VERSION] session_version=%s published_version=%s current_version=%s",
        session_version,
        published_version_number,
        current_version_number,
    )
    if runtime_session:
        runtime_nodes = runtime_graph.get("nodes") if isinstance(runtime_graph, dict) else []
        logger.info(
            "[SESSION FLOW GRAPH] session_version=%s session_start_text=%s",
            session_version,
            _start_preview_from_nodes(runtime_nodes if isinstance(runtime_nodes, list) else []),
        )
        if published_version_number is not None and session_version is not None and str(session_version) != str(published_version_number):
            logger.warning(
                "[SESSION VERSION MISMATCH] session_version=%s published_version=%s action=reset_session_reload_published",
                session_version,
                published_version_number,
            )
            # Guard: published version changed, abort old in-memory/runtime flow and fully restart from published.
            session_service.clear_runtime_session(conversation.tenant_id, user_identifier, flow, reason="published_version_changed")
            runtime_session = None
            invalid_reason = None
            _safe_set_conversation_current_node(db, conversation, None)
            conversation.current_flow = flow.id
            invalidate_flow_runtime_cache(flow.id)
            db.flush()
            db.refresh(flow)
            runtime_graph = resolve_runtime_flow_graph(db=db, tenant_id=conversation.tenant_id, flow_id=str(flow.id))
            current_flow_version_id = _parse_uuid(runtime_graph.get("version_id") if isinstance(runtime_graph, dict) else None)
            reloaded_start_node = _get_start_node(
                db=db,
                flow_id=flow.id,
                tenant_id=conversation.tenant_id,
                runtime_graph=runtime_graph,
            )
            start_text_preview = ""
            if isinstance(runtime_graph, dict):
                runtime_nodes = runtime_graph.get("nodes")
                if isinstance(runtime_nodes, list):
                    start_text_preview = _start_preview_from_nodes(runtime_nodes)
            if reloaded_start_node:
                tenant = db.execute(select(Tenant).where(Tenant.id == conversation.tenant_id)).scalars().first()
                if not tenant:
                    logger.warning("[SESSION RESET RELOAD DONE] tenant_missing=true")
                    return None
                runtime_session = _send_start_message_on_session_restart(
                    db=db,
                    tenant=tenant,
                    conversation=conversation,
                    flow=flow,
                    start_node=reloaded_start_node,
                    runtime_graph=runtime_graph,
                    runtime_session=runtime_session,
                    session_service=session_service,
                    published_version_number=published_version_number,
                    user_identifier=user_identifier,
                )
                logger.info(
                    "[SESSION RESET RELOAD DONE] published_version=%s start_text_preview=%s",
                    published_version_number,
                    start_text_preview,
                )
            else:
                logger.warning(
                    "[SESSION RESET RELOAD DONE] published_version=%s start_text_preview=%s start_node_missing=true",
                    published_version_number,
                    start_text_preview,
                )
    if _is_reset_command(normalized_message):
        _emit_runtime_event(
            db=db,
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            flow_id=conversation.current_flow or flow.id,
            flow_version_id=current_flow_version_id,
            node_id=conversation.current_node_id,
            event_type="abandoned",
            metadata={"reason": "reset_command", "abandon_reason": "reset_command"},
        )
        session_service.clear_runtime_session(conversation.tenant_id, user_identifier, flow, reason="reset_command")
        _safe_set_conversation_current_node(db, conversation, None)
        conversation.current_flow = None
    elif runtime_session and invalid_reason:
        old_session_id = runtime_session.id
        _emit_runtime_event(
            db=db,
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            flow_id=conversation.current_flow or flow.id,
            flow_version_id=current_flow_version_id,
            node_id=conversation.current_node_id,
            event_type="abandoned",
            metadata={"reason": invalid_reason, "abandon_reason": invalid_reason},
        )
        session_service.clear_runtime_session(conversation.tenant_id, user_identifier, flow, reason=invalid_reason)
        _safe_set_conversation_current_node(db, conversation, None)
        conversation.current_flow = flow.id
        conversation.mode = "flow"
        restart_start_node = _get_start_node(
            db=db,
            flow_id=flow.id,
            tenant_id=conversation.tenant_id,
            runtime_graph=runtime_graph,
        )
        if restart_start_node:
            tenant = db.execute(select(Tenant).where(Tenant.id == conversation.tenant_id)).scalars().first()
            if not tenant:
                logger.warning("[SESSION RESET RELOAD DONE] tenant_missing=true")
                return None
            runtime_session = _send_start_message_on_session_restart(
                db=db,
                tenant=tenant,
                conversation=conversation,
                flow=flow,
                start_node=restart_start_node,
                runtime_graph=runtime_graph,
                runtime_session=runtime_session,
                session_service=session_service,
                published_version_number=published_version_number,
                user_identifier=user_identifier,
            )
            logger.info(
                "[FLOW SESSION RESTART] old_session_id=%s new_session_id=%s",
                old_session_id,
                runtime_session.id,
            )
        else:
            runtime_session = None
    elif runtime_session and runtime_session.current_node_id:
        parsed_node = _parse_uuid(runtime_session.current_node_id)
        if parsed_node:
            conversation.current_flow = flow.id
            _safe_set_conversation_current_node(db, conversation, parsed_node)
            logger.info("[SESSION CONTINUE] node_id=%s", conversation.current_node_id)

    initialized_node = _initialize_flow_start_node(
        db=db,
        conversation=conversation,
        flow_id=flow.id,
        runtime_graph=runtime_graph,
        runtime_session=runtime_session,
        session_service=session_service,
    )
    logger.info(
        "[FLOW ROUTING] session_found=%s session_id=%s",
        bool(runtime_session),
        getattr(runtime_session, "id", None),
    )
    logger.info(
        "[FLOW ROUTING] start_node_found=%s node_id=%s",
        bool(conversation.current_node_id),
        conversation.current_node_id,
    )
    if conversation.current_node_id is None and not initialized_node:
        logger.info("[FLOW ROUTING] using_fallback=true reason=start_node_missing")
        return None

    session_node_id = conversation.current_node_id
    if isinstance(initialized_node, VersionedFlowNode):
        session_node_id = initialized_node.id
    elif runtime_session and runtime_session.current_node_id:
        parsed_node = _parse_uuid(runtime_session.current_node_id)
        if parsed_node:
            session_node_id = parsed_node

    runtime_session = session_service.save_runtime_session(
        tenant_id=conversation.tenant_id,
        user_identifier=user_identifier,
        flow=flow,
        current_node_id=session_node_id,
        context=conversation.context if isinstance(conversation.context, dict) else {},
    )

    session_variables = dict(runtime_session.variables or {})
    flow_started_emitted = bool(session_variables.get("analytics.flow_started_emitted"))
    if not flow_started_emitted:
        _emit_runtime_event(
            db=db,
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            flow_id=flow.id,
            flow_version_id=current_flow_version_id,
            node_id=conversation.current_node_id,
            event_type="flow_started",
            metadata={
                "source": "runtime_session_initialized",
                "flow_version_id": str(current_flow_version_id) if current_flow_version_id else None,
                "node_id": str(conversation.current_node_id) if conversation.current_node_id else None,
            },
            dedupe_bucket_seconds=30,
        )
        runtime_session = session_service.save_runtime_session(
            tenant_id=conversation.tenant_id,
            user_identifier=user_identifier,
            flow=flow,
            current_node_id=session_node_id,
            context=runtime_session.context if isinstance(runtime_session.context, dict) else {},
            variables={"analytics.flow_started_emitted": True},
        )

    session_conversion_emitted = bool(session_variables.get("conversion_at"))

    emit_message_received_event(
        db=db,
        tenant_id=conversation.tenant_id,
        conversation_id=conversation.id,
        flow_id=flow.id,
        flow_version_id=current_flow_version_id,
        node_id=conversation.current_node_id,
        message_text=message_text,
        source="entry_handler",
        input_kind="text",
        dedupe_bucket_seconds=10,
    )
    first_flow_turn = not had_active_session
    intent: str | None = None
    if conversation.mode != "flow":
        intent = detect_intent(message_text or "")
        logger.info("[INTENT] detected=%s", intent)
        if intent:
            conversation.context["intent"] = intent
    else:
        logger.info("[INTENT] skipped (in flow mode)")
        intent = conversation.context.get("intent")

    logger.info(
        "[STATE FULL] mode=%s node=%s intent=%s retries=%s",
        conversation.mode,
        conversation.current_node_id,
        conversation.context.get("intent"),
        conversation.retries,
    )
    _sanitize_conversation_current_node(db, conversation)
    db.commit()
    db.refresh(conversation)

    if force_node:
        _set_flow_mode(db=db, conversation=conversation, flow_id=flow.id, node_id=force_node)
        logger.info(
            "Flow retomado apos delay conversation_id=%s force_node=%s",
            conversation.id,
            force_node,
        )
    elif conversation.current_node_id:
        if conversation.mode != "flow" or conversation.current_flow != flow.id:
            conversation.mode = "flow"
            conversation.current_flow = flow.id
            db.add(conversation)
            db.commit()
            db.refresh(conversation)
        logger.info("[FLOW CONTINUE] node_id=%s", conversation.current_node_id)
        logger.info("[FLOW PRIORITY] mantendo fluxo atual current_node_id=%s", conversation.current_node_id)
    else:
        if conversation.mode == "flow" and conversation.current_flow and conversation.current_node_id is None:
            logger.warning("[FLOW ERROR] no current node, trying to recover")
            start_node = _get_start_node(
                db=db,
                flow_id=flow.id,
                tenant_id=conversation.tenant_id,
                runtime_graph=runtime_graph,
            )
            if start_node:
                set_current_node(conversation=conversation, node_id=start_node.id, db=db)
                logger.info("[FLOW RECOVERY] node=%s", start_node.id)
            else:
                logger.error("[FLOW ERROR] no start node found")
                return None

        if not intent:
            conversation.retries = (conversation.retries or 0) + 1
            if conversation.retries >= MAX_RETRIES:
                logger.info("[FALLBACK LIMIT] exceeded → reset")
                _emit_runtime_event(
                    db=db,
                    tenant_id=conversation.tenant_id,
                    conversation_id=conversation.id,
                    flow_id=conversation.current_flow,
                    flow_version_id=current_flow_version_id,
                    node_id=conversation.current_node_id,
                    event_type="abandoned",
                    metadata={"reason": "fallback_limit_exceeded", "abandon_reason": "fallback_limit_exceeded"},
                )
                if runtime_session:
                    session_service.end_session(
                        runtime_session,
                        status="abandoned",
                    )
                _reset_to_bot_mode(db=db, conversation=conversation, reason="fallback_limit_exceeded")
                conversation.retries = 0
                db.commit()
                db.refresh(conversation)
                logger.info(
                    "[STATE FULL] mode=%s node=%s intent=%s retries=%s",
                    conversation.mode,
                    conversation.current_node_id,
                    conversation.context.get("intent") if isinstance(conversation.context, dict) else None,
                    conversation.retries,
                )
                return (
                    "Ainda não consegui identificar o que você precisa. "
                    "Vamos recomeçar: me diga se você quer vender mais, automatizar atendimento ou integrar com sistema."
                )
            fallback_text = (
                "Boa 👌 Me fala melhor o que você quer fazer:\n"
                "📈 vender mais\n"
                "🤖 automatizar atendimento\n"
                "🔗 integrar com sistema"
            )
            logger.info("[FALLBACK] triggered")
            logger.info("[FALLBACK] retries=%s", conversation.retries)
            _emit_runtime_event(
                db=db,
                tenant_id=conversation.tenant_id,
                conversation_id=conversation.id,
                flow_id=conversation.current_flow,
                flow_version_id=current_flow_version_id,
                node_id=conversation.current_node_id,
                event_type="abandoned",
                metadata={"reason": "fallback", "abandon_reason": "fallback"},
                dedupe_bucket_seconds=30,
            )
            db.commit()
            db.refresh(conversation)
            return fallback_text

        start_node = _get_start_node(
            db=db,
            flow_id=flow.id,
            tenant_id=conversation.tenant_id,
            runtime_graph=runtime_graph,
        )
        if not start_node:
            return None

        start_edges = _get_edges(
            db=db,
            flow_id=flow.id,
            source=start_node.id,
            runtime_graph=runtime_graph,
        )
        selected_start_edge = None
        for edge in start_edges:
            edge_condition = _normalize_text(edge.condition)
            if intent == edge_condition or (intent and edge_condition and intent in edge_condition):
                selected_start_edge = edge
                break

        if not conversation.current_node_id:
            start_node = _get_start_node(
                db=db,
                flow_id=flow.id,
                tenant_id=conversation.tenant_id,
                runtime_graph=runtime_graph,
            )
            if start_node:
                conversation.mode = "flow"
                conversation.current_flow = flow.id
                set_current_node(conversation=conversation, node_id=start_node.id, db=db)
                print(f"[FLOW INIT] start_node_id={start_node.id}")
                logger.info("[FLOW INIT] start_node_id=%s", start_node.id)
                logger.info("[FLOW RECOVERY] node=%s", start_node.id)
            else:
                print("[FLOW ERROR] no start node found")
                logger.error("[FLOW ERROR] no start node found")
                return None

        if conversation.mode != "flow":
            if not intent:
                conversation.retries = (conversation.retries or 0) + 1
                fallback_text = (
                    "Boa 👌 Me fala melhor o que você quer fazer:\n"
                    "📈 vender mais\n"
                    "🤖 automatizar atendimento\n"
                    "🔗 integrar com sistema"
                )
                logger.info("[FALLBACK] triggered")
                logger.info("[FALLBACK] retries=%s", conversation.retries)
                _emit_runtime_event(
                    db=db,
                    tenant_id=conversation.tenant_id,
                    conversation_id=conversation.id,
                    flow_id=conversation.current_flow,
                    flow_version_id=current_flow_version_id,
                    node_id=conversation.current_node_id,
                    event_type="abandoned",
                    metadata={"reason": "fallback", "abandon_reason": "fallback"},
                    dedupe_bucket_seconds=30,
                )
                db.commit()
                db.refresh(conversation)
                return fallback_text

            start_node = _get_start_node(
                db=db,
                flow_id=flow.id,
                tenant_id=conversation.tenant_id,
                runtime_graph=runtime_graph,
            )
            if not start_node:
                return None

            start_edges = _get_edges(
                db=db,
                flow_id=flow.id,
                source=start_node.id,
                runtime_graph=runtime_graph,
                runtime_session=runtime_session,
                session_service=session_service,
                flow_version_id=current_flow_version_id,
                user_identifier=user_identifier,
                flow=flow,
            )
            selected_start_edge = None
            for edge in start_edges:
                edge_condition = _normalize_text(edge.condition)
                if intent == edge_condition or (intent and edge_condition and intent in edge_condition):
                    selected_start_edge = edge
                    break

            selected_start_node_id = selected_start_edge.target if selected_start_edge else start_node.id
            _set_flow_mode(db=db, conversation=conversation, flow_id=flow.id, node_id=selected_start_node_id)
            logger.info("[FLOW STATE] current=%s next=%s", conversation.current_node_id, selected_start_node_id)

    if conversation.mode == "flow":
        _keep_flow_mode(conversation)

    if first_flow_turn:
        logger.info("[FLOW RUNTIME] new_session=true start_node=%s", conversation.current_node_id)

    tenant = db.execute(select(Tenant).where(Tenant.id == conversation.tenant_id)).scalars().first()
    if not tenant:
        logger.warning("[FLOW SEND] Tenant nao encontrado para conversation_id=%s", conversation.id)
        return None

    conversation_phone = getattr(conversation, "phone", None) or conversation.phone_number

    if not conversation.current_node_id:
        logger.warning("[FLOW ERROR] no current node, trying to recover")
        start_node = _get_start_node(
            db=db,
            flow_id=flow.id,
            tenant_id=conversation.tenant_id,
            runtime_graph=runtime_graph,
        )
        if start_node:
            set_current_node(conversation=conversation, node_id=start_node.id, db=db)
            logger.info("[FLOW RECOVERY] node=%s", start_node.id)
        else:
            logger.error("[FLOW ERROR] no start node found")
            return None

    node = _get_node(
        db=db,
        node_id=conversation.current_node_id,
        tenant_id=conversation.tenant_id,
        runtime_graph=runtime_graph,
    )
    if node:
        preview = (_resolve_node_text(_extract_node_data(node)) or "").strip().replace("\n", " ")
        logger.info("[FLOW START EXECUTE] node_id=%s text_preview=%s", node.id, preview[:80])
        logger.info("[FLOW MODE KEEP] mode=flow reason=start_node_found")
    if not node:
        if _is_greeting(normalized_message):
            session_service.clear_runtime_session(conversation.tenant_id, user_identifier, flow, reason="node_missing_on_greeting")
        _reset_to_bot_mode(db=db, conversation=conversation, reason="flow_error_node_not_found")
        return None

    collected_messages: list[str] = []
    consumed_start_message = False
    visited_node_ids: set[uuid.UUID] = set()
    reached_max_steps = True
    for step_index in range(MAX_AUTO_STEPS):
        logger.info(
            "event=flow_step tenant_id=%s conversation_id=%s step=%s current_node_id=%s",
            conversation.tenant_id,
            conversation.id,
            step_index + 1,
            conversation.current_node_id,
        )
        node_data = _extract_node_data(node)
        if node.id in visited_node_ids:
            logger.warning(
                "event=flow_loop_detected tenant_id=%s conversation_id=%s node_id=%s",
                conversation.tenant_id,
                conversation.id,
                node.id,
            )
            _reset_to_bot_mode(db=db, conversation=conversation, reason="flow_loop_detected")
            reached_max_steps = False
            break
        visited_node_ids.add(node.id)
        print(f"[FLOW DEBUG] node.type={node.type}")
        print(f"[FLOW DEBUG] node.data={getattr(node, 'data', None) or node_data}")

        edges = _get_edges(
            db=db,
            flow_id=node.flow_id,
            source=node.id,
            runtime_graph=runtime_graph,
        )
        node_type = str(node.type or "").strip().lower()
        if node_type.endswith("node"):
            node_type = node_type[:-4]
        node_entered_source = "manual_resume" if force_node else "runtime"
        logger.info("Node executado conversation_id=%s node_id=%s node_type=%s", conversation.id, node.id, node_type)
        _emit_node_entered_event(
            db=db,
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            flow_id=node.flow_id,
            flow_version_id=current_flow_version_id,
            node=node,
            node_data=node_data,
            edges=edges,
            step=step_index + 1,
            source=node_entered_source,
        )

        if node_type in {"message", "text", "msg", "start"}:
            text = _resolve_node_text(node_data)
            if node_type in {"message", "text", "msg"}:
                if not text:
                    print("[FLOW ERROR] texto vazio no node")
                    return None
                _send_flow_whatsapp_message(tenant=tenant, phone=conversation_phone, text=text)
                if first_flow_turn and not consumed_start_message:
                    logger.info("[FLOW RUNTIME] sent_start_message=%s", text)
                    logger.info(
                        "[FLOW START CONTENT] node_id=%s source=%s text_preview=%s",
                        node.id,
                        (runtime_graph or {}).get("source", "unknown"),
                        _text_preview(text),
                    )
                    consumed_start_message = True
                _emit_runtime_event(
                    db=db,
                    tenant_id=conversation.tenant_id,
                    conversation_id=conversation.id,
                    flow_id=node.flow_id,
                    flow_version_id=current_flow_version_id,
                    node_id=node.id,
                    event_type="message_sent",
                    metadata={"channel": "whatsapp"},
                    dedupe_bucket_seconds=10,
                )
                # Após enviar mensagem, zera msg para que nodes seguintes
                # (condition, choice) não usem a mensagem inicial do usuário
                msg = ""
            elif text:
                collected_messages.append(text)
            next_edge = _pick_default_edge(edges)
            next_node_id = next_edge.target if next_edge else None
            logger.info("[FLOW NEXT NODE] current_node_id=%s next_node_id=%s", node.id, next_node_id)
            print(f"[current_node_id] {node.id}")
            print(f"[next_node_id] {next_node_id}")
            node = _advance_to_edge_target(
                # primeira mensagem só inicializa o fluxo e envia o start node
                db=db,
                conversation=conversation,
                edge=next_edge,
                runtime_graph=runtime_graph,
                runtime_session=runtime_session,
                session_service=session_service,
                flow_version_id=current_flow_version_id,
                user_identifier=user_identifier,
                flow=flow,
            )
            if node and session_service:
                runtime_session = session_service.save_runtime_session(
                    tenant_id=conversation.tenant_id,
                    user_identifier=user_identifier,
                    flow=flow,
                    current_node_id=node.id,
                    context=conversation.context if isinstance(conversation.context, dict) else {},
                    status="running",
                )
            if not node:
                reached_max_steps = False
                break
            if first_flow_turn and consumed_start_message:
                logger.info("[FLOW RUNTIME] next_node=%s", getattr(node, "id", None))
                break
            continue

        if node_type in {"choice", "question"}:
            buttons = node_data.get("buttons") if isinstance(node_data.get("buttons"), list) else []

            expected_options = []
            for button in buttons:
                if isinstance(button, dict) and button.get("label"):
                    expected_options.append(_normalize_text(str(button["label"])))

            edge_labels = [
                _normalize_text(edge.condition)
                for edge in edges
                if edge.condition and _normalize_text(edge.condition)
            ]
            options = expected_options or edge_labels

            # Usuario ainda nao respondeu — envia a pergunta com botoes e aguarda
            if not msg:
                text = _resolve_node_text(node_data)
                if not text:
                    text = _render_choice_prompt(node_data=node_data, edges=edges).strip()

                if text:
                    if buttons and len(buttons) <= 3:
                        _send_flow_interactive_buttons(
                            tenant=tenant,
                            phone=conversation_phone,
                            text=text,
                            buttons=buttons,
                        )
                    else:
                        _send_flow_whatsapp_message(tenant=tenant, phone=conversation_phone, text=text)
                if first_flow_turn and not consumed_start_message:
                    logger.info("[FLOW RUNTIME] sent_start_message=%s", text)
                    logger.info(
                        "[FLOW START CONTENT] node_id=%s source=%s text_preview=%s",
                        node.id,
                        (runtime_graph or {}).get("source", "unknown"),
                        _text_preview(text),
                    )
                    consumed_start_message = True
                else:
                    print("[FLOW ERROR] node choice sem texto")

                # Persiste o node atual como ponto de espera da resposta
                set_current_node(conversation=conversation, node_id=node.id, db=db)
                reached_max_steps = False
                break

            # Usuario respondeu — tenta match com as edges
            selected_edge = None
            for edge in edges:
                condition = _normalize_text(edge.condition)
                if not condition:
                    continue
                # match exato (handleId do botao) ou por substring
                if condition == msg or condition in msg or msg in condition:
                    selected_edge = edge
                    break

            # Resposta nao bate com nenhuma opcao — reenvia a pergunta
            if not selected_edge and options:
                text = _resolve_node_text(node_data)
                if not text:
                    text = _render_choice_prompt(node_data=node_data, edges=edges).strip()
                if text:
                    if buttons and len(buttons) <= 3:
                        _send_flow_interactive_buttons(
                            tenant=tenant,
                            phone=conversation_phone,
                            text=text,
                            buttons=buttons,
                        )
                    else:
                        _send_flow_whatsapp_message(tenant=tenant, phone=conversation_phone, text=text)
                if first_flow_turn and not consumed_start_message:
                    logger.info("[FLOW RUNTIME] sent_start_message=%s", text)
                    logger.info(
                        "[FLOW START CONTENT] node_id=%s source=%s text_preview=%s",
                        node.id,
                        (runtime_graph or {}).get("source", "unknown"),
                        _text_preview(text),
                    )
                    consumed_start_message = True
                else:
                    print("[FLOW ERROR] node choice sem texto")

                set_current_node(conversation=conversation, node_id=node.id, db=db)
                reached_max_steps = False
                break

            node = _advance_to_edge_target(
                # primeira mensagem só inicializa o fluxo e envia o start node
                db=db,
                conversation=conversation,
                edge=selected_edge or _pick_default_edge(edges),
                runtime_graph=runtime_graph,
                runtime_session=runtime_session,
                session_service=session_service,
                flow_version_id=current_flow_version_id,
                user_identifier=user_identifier,
                flow=flow,
            )
            if not node:
                reached_max_steps = False
                break
            continue

        if node_type == "condition":
            print(f"[FLOW CHECK] avaliando node: {node.id}")
            logger.info("[FLOW RUNTIME] evaluating_condition=%s", node.id)
            logger.info("[FLOW CHECK] avaliando node=%s conversation_id=%s", node.id, conversation.id)
            raw_condition = str(node_data.get("condition") or node_data.get("content") or "")

            # Sem mensagem do usuário — para e aguarda resposta
            if not msg:
                print(f"[FLOW CONDITION WAIT] aguardando resposta no node={node.id}")
                set_current_node(conversation=conversation, node_id=node.id, db=db)
                reached_max_steps = False
                break

            raw_input = message_text or ""
            normalized_input = _normalize_text(raw_input)

            # Suporte a múltiplas palavras/sinônimos separados por vírgula
            # Exemplo: "vender, vendas, comercial, quero vender"
            keywords = [
                normalized_kw
                for kw in raw_condition.split(",")
                if (normalized_kw := _normalize_text(kw))
            ]

            match_result = _match_condition_input(normalized_input, keywords)
            result = bool(match_result)
            matched_keyword = _find_matched_keyword(normalized_input, keywords) if result else None

            print(f"[CONDITION INPUT RAW] {raw_input}")
            print(f"[CONDITION INPUT NORMALIZED] {normalized_input}")
            print(f"[CONDITION KEYWORDS RAW] {raw_condition}")
            print(f"[CONDITION KEYWORDS NORMALIZED] {keywords}")
            print(f"[CONDITION MATCH] {result}")
            logger.info("[CONDITION INPUT RAW] %s", raw_input)
            logger.info("[CONDITION INPUT NORMALIZED] %s", normalized_input)
            logger.info("[CONDITION KEYWORDS RAW] %s", raw_condition)
            logger.info("[CONDITION KEYWORDS NORMALIZED] %s", keywords)
            logger.info("[CONDITION MATCH] %s", result)
            if result:
                print(f"[FLOW MATCH] condição TRUE: {node.id}")
                logger.info("[FLOW MATCH] condicao TRUE node=%s conversation_id=%s", node.id, conversation.id)
                if runtime_session and not session_conversion_emitted:
                    _emit_runtime_event(
                        db=db,
                        tenant_id=conversation.tenant_id,
                        conversation_id=conversation.id,
                        flow_id=node.flow_id,
                        flow_version_id=current_flow_version_id,
                        node_id=node.id,
                        event_type="conversion",
                        metadata={"trigger": "condition_match"},
                        dedupe_bucket_seconds=30,
                    )
                    session_service.end_session(runtime_session, status="conversion")
                    session_conversion_emitted = True
            else:
                print(f"[FLOW MISS] condição FALSE: {node.id}")
                logger.info("[FLOW MISS] condicao FALSE node=%s conversation_id=%s", node.id, conversation.id)

            true_edge, false_edge = _resolve_condition_routes(edges)
            true_node_id = true_edge.target if true_edge else None
            false_node_id = false_edge.target if false_edge else None
            selected_edge = true_edge if result else false_edge
            selected_next = true_node_id if result else false_node_id
            route_label = "true" if result else "false"
            print(f"[CONDITION EDGE SELECTED] {route_label} target_id={selected_next}")
            logger.info("[CONDITION EDGE SELECTED] %s target_id=%s", route_label, selected_next)
            _emit_runtime_event(
                db=db,
                tenant_id=conversation.tenant_id,
                conversation_id=conversation.id,
                flow_id=node.flow_id,
                flow_version_id=current_flow_version_id,
                node_id=node.id,
                event_type="condition_matched",
                metadata={
                    "result": result,
                    "matched_keyword": matched_keyword,
                    "route_label": route_label,
                    "source_node_id": str(node.id),
                    "target_node_id": str(selected_next) if selected_next else None,
                },
            )

            node = _advance_to_edge_target(
                # primeira mensagem só inicializa o fluxo e envia o start node
                db=db,
                conversation=conversation,
                edge=selected_edge,
                runtime_graph=runtime_graph,
                runtime_session=runtime_session,
                session_service=session_service,
                flow_version_id=current_flow_version_id,
                user_identifier=user_identifier,
                flow=flow,
            )
            if not node:
                reached_max_steps = False
                break

            # Condição resolvida por edge (true/false) — interrompe avaliação atual
            # para manter execução determinística conforme o caminho visual.
            continue

        if node_type == "delay":
            logger.info("[DELAY NODE HIT] node_id=%s", node.id)
            raw_delay = node_data.get("delay") or node_data.get("seconds") or node_data.get("duration") or node_data.get("content") or node.content
            try:
                delay_seconds = int(float(str(raw_delay).strip()))
            except Exception:
                logger.warning("[DELAY INVALID] node_id=%s raw=%s fallback=1", node.id, raw_delay)
                delay_seconds = 1
            if delay_seconds <= 0:
                logger.warning("[DELAY INVALID] node_id=%s raw=%s fallback=1", node.id, raw_delay)
                delay_seconds = 1
            logger.info("[DELAY SECONDS] %s", delay_seconds)

            next_edge = _pick_default_edge(edges)
            if not next_edge:
                logger.info("Delay sem proxima aresta conversation_id=%s node_id=%s", conversation.id, node.id)
                _emit_runtime_event(
                    db=db,
                    tenant_id=conversation.tenant_id,
                    conversation_id=conversation.id,
                    flow_id=node.flow_id,
                    flow_version_id=current_flow_version_id,
                    node_id=node.id,
                    event_type="flow_completed",
                    metadata={"completion_reason": "delay_without_next"},
                    dedupe_bucket_seconds=30,
                )
                if runtime_session:
                    session_service.end_session(runtime_session, status="completed")
                _reset_to_bot_mode(db=db, conversation=conversation, reason="flow_finished_delay_without_next")
                reached_max_steps = False
                break

            logger.info("[DELAY CONTINUE TO] next_node_id=%s", next_edge.target)
            if delay_seconds <= 5:
                time.sleep(delay_seconds)
                set_current_node(conversation=conversation, node_id=next_edge.target, db=db)
                _keep_flow_mode(conversation)
                node = _find_node_by_id(nodes, next_edge.target)
                if not node:
                    reached_max_steps = False
                    break
                logger.info("[DELAY RESPONSE NODE] node_id=%s", node.id)
                continue

            enqueue_delay(
                tenant_id=conversation.tenant_id,
                phone=conversation.phone_number,
                next_node_id=next_edge.target,
                seconds=delay_seconds,
            )
            logger.info("[FLOW STATE] current=%s next=%s", conversation.current_node_id, next_edge.target)
            set_current_node(conversation=conversation, node_id=next_edge.target, db=db)
            _keep_flow_mode(conversation)
            reached_max_steps = False
            break

        if node_type == "action":
            action_name = str(node_data.get("action") or "").strip()
            content = str(node_data.get("content") or "").strip()
            if runtime_session and (not session_conversion_emitted) and _is_conversion_node(node, node_data, flow):
                _emit_runtime_event(
                    db=db,
                    tenant_id=conversation.tenant_id,
                    conversation_id=conversation.id,
                    flow_id=node.flow_id,
                    flow_version_id=current_flow_version_id,
                    node_id=node.id,
                    event_type="conversion",
                    metadata={"trigger": "action_conversion_node"},
                    dedupe_bucket_seconds=30,
                )
                session_service.end_session(runtime_session, status="conversion")
                session_conversion_emitted = True
            if content:
                collected_messages.append(content)
            elif action_name:
                collected_messages.append(f"Acao executada: {action_name}")

            node = _advance_to_edge_target(
                # primeira mensagem só inicializa o fluxo e envia o start node
                db=db,
                conversation=conversation,
                edge=_pick_default_edge(edges),
                runtime_graph=runtime_graph,
                runtime_session=runtime_session,
                session_service=session_service,
                flow_version_id=current_flow_version_id,
                user_identifier=user_identifier,
                flow=flow,
            )
            if not node:
                reached_max_steps = False
                break
            continue

        if runtime_session and _is_terminal_node(node_data, edges):
            _emit_runtime_event(
                db=db,
                tenant_id=conversation.tenant_id,
                conversation_id=conversation.id,
                flow_id=node.flow_id,
                flow_version_id=current_flow_version_id,
                node_id=node.id,
                event_type="flow_completed",
                metadata={"completion_reason": "terminal_node"},
                dedupe_bucket_seconds=30,
            )
            session_service.end_session(runtime_session, status="completed")
            _reset_to_bot_mode(db=db, conversation=conversation, reason="flow_finished_terminal_node")
            reached_max_steps = False
            break

        content = (node_data.get("content") or "").strip()
        if content:
            collected_messages.append(content)
        node = _advance_to_edge_target(
            db=db,
            conversation=conversation,
            edge=_pick_default_edge(edges),
            runtime_graph=runtime_graph,
            runtime_session=runtime_session,
            session_service=session_service,
            flow_version_id=current_flow_version_id,
        )
        if not node:
            reached_max_steps = False
            break

    if reached_max_steps and node is not None:
        logger.warning(
            "event=flow_max_steps_reached tenant_id=%s conversation_id=%s max_steps=%s node_id=%s",
            conversation.tenant_id,
            conversation.id,
            MAX_AUTO_STEPS,
            node.id,
        )
        _reset_to_bot_mode(db=db, conversation=conversation, reason="flow_max_steps_reached")

    return "\n\n".join(part for part in collected_messages if part).strip() or None


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

    runtime_graph = resolve_runtime_flow_graph(db=db, tenant_id=tenant_id, flow_id=str(flow.id))
    runtime_nodes = runtime_graph.get("nodes") if isinstance(runtime_graph, dict) else []
    runtime_edges = runtime_graph.get("edges") if isinstance(runtime_graph, dict) else []
    if isinstance(runtime_nodes, list) and runtime_nodes:
        return {
            "flow_id": str(flow.id),
            "version_id": runtime_graph.get("version_id"),
            "source": "flow_versions",
            "nodes": runtime_nodes,
            "edges": runtime_edges if isinstance(runtime_edges, list) else [],
        }
    return {
        "flow_id": str(flow.id),
        "version_id": runtime_graph.get("version_id"),
        "source": runtime_graph.get("source") or "empty",
        "nodes": runtime_nodes if isinstance(runtime_nodes, list) else [],
        "edges": runtime_edges if isinstance(runtime_edges, list) else [],
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
        version=next_version,
        nodes=nodes_payload,
        edges=edges_payload,
        is_active=True,
    )
    db.add(flow_version)
    db.flush()
    flow.current_version_id = flow_version.id
    if flow.published_version_id is None:
        flow.published_version_id = flow_version.id
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

    node_id_map: dict[str, uuid.UUID] = {}
    for item in nodes_payload:
        raw_id = str(item.get("id") or "").strip()
        node_id = uuid.uuid4()
        if raw_id:
            try:
                node_id = uuid.UUID(raw_id)
            except ValueError:
                pass

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
        node_id_map[raw_id or str(node_id)] = node_id

    db.flush()

    for item in edges_payload:
        source_raw = str(item.get("source") or "").strip()
        target_raw = str(item.get("target") or "").strip()
        source_id = node_id_map.get(source_raw)
        target_id = node_id_map.get(target_raw)
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
