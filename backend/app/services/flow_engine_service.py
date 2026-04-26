from __future__ import annotations

import unicodedata
import uuid
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.models import Conversation, Flow, FlowEdge, FlowNode, FlowVersion, Tenant
from app.services.delay_queue_service import enqueue_delay
from app.services.flow_analytics_service import FALLBACK, FLOW_FINISH, FLOW_MATCH, FLOW_SEND, FLOW_START, record_flow_event
from app.services.queue import enqueue_send_message
from app.utils.phone import normalize_phone

DEFAULT_FLOW_NAME = "__default_visual__"
MAX_AUTO_STEPS = 10
MAX_RETRIES = 3
logger = logging.getLogger(__name__)


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


def _get_current_flow_runtime(db: Session, flow: Flow, tenant_id: uuid.UUID) -> dict[str, Any] | None:
    if not flow.current_version_id:
        return None
    flow_version = db.execute(
        select(FlowVersion).where(FlowVersion.id == flow.current_version_id, FlowVersion.flow_id == flow.id)
    ).scalars().first()
    if not flow_version:
        return None
    return _load_flow_version_runtime(flow=flow, tenant_id=tenant_id, flow_version=flow_version)


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    # Remove pontuação e espaços extras para match robusto
    cleaned = "".join(ch for ch in without_accents if ch.isalnum() or ch.isspace())
    return " ".join(cleaned.lower().split())


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


def _extract_node_data(node: FlowNode | VersionedFlowNode) -> dict[str, Any]:
    metadata = node.metadata_json or {}
    return {
        "label": metadata.get("label") or node.content or node.type,
        "text": node.content or metadata.get("text"),
        "content": node.content,
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
    flow = db.execute(
        select(Flow.id)
        .where(Flow.tenant_id == tenant_id)
        .order_by(Flow.created_at.asc(), Flow.id.asc())
        .limit(1)
    ).scalar_one_or_none()
    if not flow:
        return False

    node = db.execute(
        select(FlowNode.id)
        .where(FlowNode.tenant_id == tenant_id, FlowNode.flow_id == flow)
        .limit(1)
    ).scalar_one_or_none()
    return bool(node)


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


def _find_start_node(nodes: list[dict[str, Any]]) -> dict[str, Any] | None:
    # 1. prioridade: novo sistema com flag isStart
    for node in nodes:
        if node.get("data", {}).get("isStart") is True:
            return node

    # 2. fallback: fluxo antigo com choice "Inicio"
    for node in nodes:
        if (
            node.get("type") == "choice"
            and str(node.get("data", {}).get("label", "")).lower() == "inicio"
        ):
            return node

    return None


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
            "id": str(node.id),
            "type": node.type,
            "isStart": bool((node.metadata_json or {}).get("isStart")),
        }
        for node in nodes
    ]
    print(f"[FLOW INIT CHECK] nodes={check_payload}")
    logger.info("[FLOW INIT CHECK] nodes=%s", check_payload)

    start_node = find_start_node({"nodes": nodes})
    if start_node:
        print(f"[FLOW INIT FOUND] node_id={start_node.id}")
        logger.info("[FLOW INIT FOUND] node_id=%s", start_node.id)
        return start_node

    return nodes[0] if nodes else None


def _initialize_flow_start_node(
    db: Session,
    conversation: Conversation,
    flow_id: uuid.UUID,
    runtime_graph: dict[str, Any] | None = None,
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
            "id": node.id,
            "type": node.type,
            "data": node.metadata_json or {},
        }
        for node in nodes
    ]

    if conversation.current_node_id is None:
        start_node = _find_start_node(node_payload)
        if start_node:
            conversation.current_node_id = start_node["id"]
            db.add(conversation)
            db.commit()
            db.refresh(conversation)
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
        if edge_condition in {"true", "sim", "yes"} and not true_edge:
            true_edge = edge
            continue
        if edge_condition in {"false", "nao", "não", "no"} and not false_edge:
            false_edge = edge

    return true_edge, false_edge


def _set_flow_mode(db: Session, conversation: Conversation, flow_id: uuid.UUID, node_id: uuid.UUID) -> None:
    conversation.mode = "flow"
    conversation.current_flow = flow_id
    set_current_node(conversation=conversation, node_id=node_id, db=db)
    logger.info("[MODE SET] flow conversation_id=%s node_id=%s", conversation.id, node_id)


def _keep_flow_mode(conversation: Conversation) -> None:
    logger.info("[MODE KEEP] flow conversation_id=%s node_id=%s", conversation.id, conversation.current_node_id)
    if conversation.mode == "flow" and conversation.current_node_id:
        logger.info("[MODE PROTECTED] mantendo modo flow durante execução")


def _ensure_conversation_state(conversation: Conversation, message_text: str) -> None:
    if not getattr(conversation, "context", None) or not isinstance(conversation.context, dict):
        conversation.context = {}

    if getattr(conversation, "retries", None) is None:
        conversation.retries = 0

    conversation.last_input = message_text or ""


def set_current_node(conversation: Conversation, node_id: uuid.UUID | None, db: Session) -> None:
    conversation.current_node_id = node_id
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    logger.info("[FLOW STATE SET] node=%s", node_id)


def _reset_to_bot_mode(db: Session, conversation: Conversation, reason: str) -> None:
    if reason.startswith("flow_finished") and conversation.current_flow:
        record_flow_event(
            db=db,
            tenant_id=conversation.tenant_id,
            conversation_id=conversation.id,
            flow_id=conversation.current_flow,
            node_id=conversation.current_node_id,
            event_type=FLOW_FINISH,
        )

    conversation.mode = "bot"
    conversation.current_flow = None
    set_current_node(conversation=conversation, node_id=None, db=db)
    db.commit()
    db.refresh(conversation)
    logger.info("[MODE RESET] bot conversation_id=%s reason=%s", conversation.id, reason)


def _advance_to_edge_target(
    db: Session,
    conversation: Conversation,
    edge: FlowEdge | VersionedFlowEdge | None,
    runtime_graph: dict[str, Any] | None = None,
) -> FlowNode | VersionedFlowNode | None:
    if not edge:
        logger.info("Flow sem proxima aresta, encerrando fluxo conversation_id=%s", conversation.id)
        _reset_to_bot_mode(db=db, conversation=conversation, reason="flow_finished_no_next_edge")
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


def _send_flow_whatsapp_message(tenant: Tenant, phone: str, text: str) -> None:
    content = (text or "").strip()
    if not content:
        print("[FLOW ERROR] texto vazio no node")
        return

    if not phone:
        print("[FLOW ERROR] phone ausente")
        logger.warning("[FLOW SEND] Telefone ausente, mensagem nao enviada")
        return

    print(f"[FLOW SEND] Enviando: {content}")
    logger.info("[FLOW SEND] Enfileirando mensagem: %s", content)
    try:
        job_id = enqueue_send_message(tenant_id=tenant.id, phone=phone, text=content)
        print(f"[FLOW SEND RESULT] job_id={job_id}")
    except Exception as error:
        print(f"[FLOW ERROR] {error}")
        logger.exception("[FLOW SEND] Falha inesperada ao enviar mensagem no flow")


def _send_flow_interactive_buttons(tenant: Tenant, phone: str, text: str, buttons: list[dict]) -> None:
    """Enfileira envio de botoes; worker aplica fallback para texto simples se falhar."""
    print(f"[FLOW BUTTON SEND] Tentando enviar botoes: {[b.get('label') for b in buttons]}")
    try:
        job_id = enqueue_send_message(tenant_id=tenant.id, phone=phone, text=text, buttons=buttons)
        print(f"[FLOW BUTTON SEND RESULT] job_id={job_id}")
    except Exception as error:
        print(f"[FLOW BUTTON ERROR] {error} — usando fallback texto em fila")
        _send_flow_whatsapp_message(tenant=tenant, phone=phone, text=text)


def process_flow_engine(
    db: Session,
    tenant_id: uuid.UUID,
    phone: str,
    message_text: str = "",
    force_node: uuid.UUID | None = None,
    flow_id: str | None = None,
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
        flow = _get_or_create_visual_flow(db=db, tenant_id=conversation.tenant_id)
    logger.info("[FLOW SELECTED] %s", flow_id or str(flow.id))
    runtime_graph = _get_current_flow_runtime(db=db, flow=flow, tenant_id=conversation.tenant_id)
    initialized_node = _initialize_flow_start_node(
        db=db,
        conversation=conversation,
        flow_id=flow.id,
        runtime_graph=runtime_graph,
    )
    if conversation.current_node_id is None and not initialized_node:
        return None

    msg = _normalize_text(message_text)
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
                record_flow_event(
                    db=db,
                    tenant_id=conversation.tenant_id,
                    conversation_id=conversation.id,
                    flow_id=conversation.current_flow,
                    node_id=conversation.current_node_id,
                    event_type=FALLBACK,
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
            record_flow_event(
                db=db,
                tenant_id=conversation.tenant_id,
                conversation_id=conversation.id,
                flow_id=conversation.current_flow,
                node_id=conversation.current_node_id,
                event_type=FALLBACK,
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
                record_flow_event(
                    db=db,
                    tenant_id=conversation.tenant_id,
                    conversation_id=conversation.id,
                    flow_id=flow.id,
                    node_id=start_node.id,
                    event_type=FLOW_START,
                )
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
                record_flow_event(
                    db=db,
                    tenant_id=conversation.tenant_id,
                    conversation_id=conversation.id,
                    flow_id=conversation.current_flow,
                    node_id=conversation.current_node_id,
                    event_type=FALLBACK,
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

            selected_start_node_id = selected_start_edge.target if selected_start_edge else start_node.id
            _set_flow_mode(db=db, conversation=conversation, flow_id=flow.id, node_id=selected_start_node_id)
            logger.info("[FLOW STATE] current=%s next=%s", conversation.current_node_id, selected_start_node_id)
            record_flow_event(
                db=db,
                tenant_id=conversation.tenant_id,
                conversation_id=conversation.id,
                flow_id=flow.id,
                node_id=selected_start_node_id,
                event_type=FLOW_START,
            )

    if conversation.mode == "flow":
        _keep_flow_mode(conversation)

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
    if not node:
        _reset_to_bot_mode(db=db, conversation=conversation, reason="flow_error_node_not_found")
        return None

    collected_messages: list[str] = []
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
        node_type = node.type
        if node_type.endswith("Node"):
            node_type = node_type[:-4]
        print(f"[FLOW DEBUG] node.type={node.type}")
        print(f"[FLOW DEBUG] node.data={getattr(node, 'data', None) or node_data}")
        logger.info("Node executado conversation_id=%s node_id=%s node_type=%s", conversation.id, node.id, node_type)

        edges = _get_edges(
            db=db,
            flow_id=node.flow_id,
            source=node.id,
            runtime_graph=runtime_graph,
        )

        if node_type in {"message", "text", "msg", "start"}:
            text = _resolve_node_text(node_data)
            if node_type in {"message", "text", "msg"}:
                if not text:
                    print("[FLOW ERROR] texto vazio no node")
                    return None
                _send_flow_whatsapp_message(tenant=tenant, phone=conversation_phone, text=text)
                record_flow_event(
                    db=db,
                    tenant_id=conversation.tenant_id,
                    conversation_id=conversation.id,
                    flow_id=node.flow_id,
                    node_id=node.id,
                    event_type=FLOW_SEND,
                )
                # Após enviar mensagem, zera msg para que nodes seguintes
                # (condition, choice) não usem a mensagem inicial do usuário
                msg = ""
            elif text:
                collected_messages.append(text)
            node = _advance_to_edge_target(
                db=db,
                conversation=conversation,
                edge=_pick_default_edge(edges),
                runtime_graph=runtime_graph,
            )
            if not node:
                reached_max_steps = False
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
                else:
                    print("[FLOW ERROR] node choice sem texto")

                set_current_node(conversation=conversation, node_id=node.id, db=db)
                reached_max_steps = False
                break

            node = _advance_to_edge_target(
                db=db,
                conversation=conversation,
                edge=selected_edge or _pick_default_edge(edges),
                runtime_graph=runtime_graph,
            )
            if not node:
                reached_max_steps = False
                break
            continue

        if node_type == "condition":
            print(f"[FLOW CHECK] avaliando node: {node.id}")
            logger.info("[FLOW CHECK] avaliando node=%s conversation_id=%s", node.id, conversation.id)
            raw_condition = str(node_data.get("condition") or node_data.get("content") or "")

            # Sem mensagem do usuário — para e aguarda resposta
            if not msg:
                print(f"[FLOW CONDITION WAIT] aguardando resposta no node={node.id}")
                set_current_node(conversation=conversation, node_id=node.id, db=db)
                reached_max_steps = False
                break

            # Suporte a múltiplas palavras/sinônimos separados por vírgula
            # Exemplo: "vender, vendas, comercial, quero vender"
            keywords = [
                _normalize_text(kw)
                for kw in raw_condition.split(",")
                if _normalize_text(kw)
            ]

            # Match TRUE se a mensagem contiver QUALQUER uma das palavras-chave
            result = any(kw and (kw in msg or msg in kw) for kw in keywords)

            print(f"[FLOW KEYWORDS] keywords={keywords} msg='{msg}' result={result}")
            logger.info(
                "[FLOW KEYWORDS] node=%s keywords=%s msg='%s' result=%s",
                node.id, keywords, msg, result
            )
            if result:
                print(f"[FLOW MATCH] condição TRUE: {node.id}")
                logger.info("[FLOW MATCH] condicao TRUE node=%s conversation_id=%s", node.id, conversation.id)
                record_flow_event(
                    db=db,
                    tenant_id=conversation.tenant_id,
                    conversation_id=conversation.id,
                    flow_id=node.flow_id,
                    node_id=node.id,
                    event_type=FLOW_MATCH,
                )
            else:
                print(f"[FLOW MISS] condição FALSE: {node.id}")
                logger.info("[FLOW MISS] condicao FALSE node=%s conversation_id=%s", node.id, conversation.id)

            true_edge, false_edge = _resolve_condition_routes(edges)
            true_node_id = true_edge.target if true_edge else None
            false_node_id = false_edge.target if false_edge else None
            selected_edge = true_edge if result else false_edge
            selected_next = true_node_id if result else false_node_id
            route_label = "TRUE" if result else "FALSE"
            print(f"[FLOW ROUTE] {route_label} → next={selected_next}")
            logger.info(
                "[FLOW ROUTE] %s -> next=%s conversation_id=%s",
                route_label,
                selected_next,
                conversation.id,
            )

            node = _advance_to_edge_target(
                db=db,
                conversation=conversation,
                edge=selected_edge,
                runtime_graph=runtime_graph,
            )
            if not node:
                reached_max_steps = False
                break

            # Condição resolvida por edge (true/false) — interrompe avaliação atual
            # para manter execução determinística conforme o caminho visual.
            continue

        if node_type == "delay":
            delay_value = str(node_data.get("content") or "").strip()
            try:
                delay_seconds = int(delay_value)
            except ValueError:
                delay_seconds = 0

            next_edge = _pick_default_edge(edges)
            if not next_edge:
                logger.info("Delay sem proxima aresta conversation_id=%s node_id=%s", conversation.id, node.id)
                _reset_to_bot_mode(db=db, conversation=conversation, reason="flow_finished_delay_without_next")
                reached_max_steps = False
                break

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
            if content:
                collected_messages.append(content)
            elif action_name:
                collected_messages.append(f"Acao executada: {action_name}")

            node = _advance_to_edge_target(
                db=db,
                conversation=conversation,
                edge=_pick_default_edge(edges),
                runtime_graph=runtime_graph,
            )
            if not node:
                reached_max_steps = False
                break
            continue

        content = (node_data.get("content") or "").strip()
        if content:
            collected_messages.append(content)
        node = _advance_to_edge_target(
            db=db,
            conversation=conversation,
            edge=_pick_default_edge(edges),
            runtime_graph=runtime_graph,
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


def get_flow_graph(db: Session, tenant_id: uuid.UUID, flow_id: str) -> dict[str, list[dict[str, Any]]]:
    flow = resolve_flow(db=db, tenant_id=tenant_id, flow_id=flow_id)
    runtime_graph = _get_current_flow_runtime(db=db, flow=flow, tenant_id=tenant_id)
    if runtime_graph:
        return {
            "flow_id": str(flow.id),
            "nodes": [
                {
                    "id": str(node.id),
                    "type": node.type,
                    "position": {"x": node.position_x or 0, "y": node.position_y or 0},
                    "data": _extract_node_data(node),
                }
                for node in runtime_graph["nodes"]
            ],
            "edges": [
                {
                    "id": str(edge.id),
                    "source": str(edge.source),
                    "target": str(edge.target),
                    "label": edge.condition,
                    "data": {"condition": edge.condition},
                }
                for edge in runtime_graph["edges"]
            ],
        }

    nodes = db.execute(
        select(FlowNode).where(FlowNode.flow_id == flow.id, FlowNode.tenant_id == tenant_id).order_by(FlowNode.created_at.asc())
    ).scalars().all()
    edges = db.execute(select(FlowEdge).where(FlowEdge.flow_id == flow.id).order_by(FlowEdge.id.asc())).scalars().all()

    return {
        "flow_id": str(flow.id),
        "nodes": [
            {
                "id": str(node.id),
                "type": node.type,
                "position": {"x": node.position_x or 0, "y": node.position_y or 0},
                "data": _extract_node_data(node),
            }
            for node in nodes
        ],
        "edges": [
            {
                "id": str(edge.id),
                "source": str(edge.source),
                "target": str(edge.target),
                "label": edge.condition,
                "data": {"condition": edge.condition},
            }
            for edge in edges
        ],
    }


def save_flow_graph(db: Session, tenant_id: uuid.UUID, flow_id: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, str]:
    flow = resolve_flow(db=db, tenant_id=tenant_id, flow_id=flow_id)
    last_version = db.query(func.max(FlowVersion.version)).filter(FlowVersion.flow_id == flow.id).scalar()
    next_version = (last_version or 0) + 1

    db.query(FlowVersion).filter(FlowVersion.flow_id == flow.id).update(
        {FlowVersion.is_active: False},
        synchronize_session=False,
    )

    flow_version = FlowVersion(
        flow_id=flow.id,
        version=next_version,
        nodes=nodes or [],
        edges=edges or [],
        is_active=True,
    )
    db.add(flow_version)
    db.flush()
    flow.current_version_id = flow_version.id
    flow.version = next_version
    db.add(flow)
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
    for item in nodes:
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

    for item in edges:
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
