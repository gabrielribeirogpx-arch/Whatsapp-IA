from __future__ import annotations

import unicodedata
import uuid
import logging
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.models import Conversation, Flow, FlowEdge, FlowNode, Tenant
from app.services.delay_queue_service import enqueue_delay
from app.utils.phone import normalize_phone
from app.services.whatsapp_service import WhatsAppConfigError, send_whatsapp_message, send_whatsapp_interactive_buttons

DEFAULT_FLOW_NAME = "__default_visual__"
MAX_AUTO_STEPS = 10
logger = logging.getLogger(__name__)


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return without_accents.lower().strip()


def _extract_node_data(node: FlowNode) -> dict[str, Any]:
    metadata = node.metadata_json or {}
    return {
        "label": metadata.get("label") or node.content or node.type,
        "text": metadata.get("text") or node.content,
        "content": node.content,
        "buttons": metadata.get("buttons") if isinstance(metadata.get("buttons"), list) else [],
        "condition": metadata.get("condition"),
        "action": metadata.get("action"),
        "metadata": metadata,
    }


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


def _get_start_node(db: Session, flow_id: uuid.UUID, tenant_id: uuid.UUID) -> FlowNode | None:
    nodes = db.execute(
        select(FlowNode)
        .where(FlowNode.flow_id == flow_id, FlowNode.tenant_id == tenant_id)
        .order_by(FlowNode.created_at.asc(), FlowNode.id.asc())
    ).scalars().all()

    for node in nodes:
        metadata = node.metadata_json or {}
        if metadata.get("isStart"):
            return node

    for node in nodes:
        if node.type in {"start", "message", "messageNode", "choice", "choiceNode", "questionNode"}:
            return node

    return nodes[0] if nodes else None


def _get_node(db: Session, node_id: uuid.UUID, tenant_id: uuid.UUID) -> FlowNode | None:
    return db.execute(
        select(FlowNode).where(FlowNode.id == node_id, FlowNode.tenant_id == tenant_id)
    ).scalars().first()


def _get_edges(db: Session, flow_id: uuid.UUID, source: uuid.UUID) -> list[FlowEdge]:
    return db.execute(
        select(FlowEdge)
        .where(FlowEdge.flow_id == flow_id, FlowEdge.source == source)
        .order_by(FlowEdge.id.asc())
    ).scalars().all()


def _pick_default_edge(edges: list[FlowEdge]) -> FlowEdge | None:
    for edge in edges:
        condition = _normalize_text(edge.condition)
        if condition in {"", "default", "else", "next"}:
            return edge
    return edges[0] if edges else None


def _set_flow_mode(db: Session, conversation: Conversation, flow_id: uuid.UUID, node_id: uuid.UUID) -> None:
    conversation.mode = "flow"
    conversation.current_flow = flow_id
    conversation.current_node_id = node_id
    db.commit()
    db.refresh(conversation)
    logger.info("[MODE SET] flow conversation_id=%s node_id=%s", conversation.id, node_id)


def _keep_flow_mode(conversation: Conversation) -> None:
    logger.info("[MODE KEEP] flow conversation_id=%s node_id=%s", conversation.id, conversation.current_node_id)


def _reset_to_bot_mode(db: Session, conversation: Conversation, reason: str) -> None:
    conversation.mode = "bot"
    conversation.current_flow = None
    conversation.current_node_id = None
    db.commit()
    db.refresh(conversation)
    logger.info("[MODE RESET] bot conversation_id=%s reason=%s", conversation.id, reason)


def _advance_to_edge_target(db: Session, conversation: Conversation, edge: FlowEdge | None) -> FlowNode | None:
    if not edge:
        logger.info("Flow sem próxima aresta, encerrando fluxo conversation_id=%s", conversation.id)
        _reset_to_bot_mode(db=db, conversation=conversation, reason="flow_finished_no_next_edge")
        return None

    next_node = _get_node(db=db, node_id=edge.target, tenant_id=conversation.tenant_id)
    logger.info(
        "Flow avançando conversation_id=%s edge=%s target_node=%s",
        conversation.id,
        edge.id,
        next_node.id if next_node else None,
    )
    conversation.current_node_id = next_node.id if next_node else None
    return next_node


def _render_choice_prompt(node_data: dict[str, Any], edges: list[FlowEdge]) -> str:
    base = (node_data.get("content") or "Escolha uma opção:").strip()
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
        logger.warning("[FLOW SEND] Telefone ausente, mensagem não enviada")
        return

    print(f"[FLOW SEND] Enviando: {content}")
    logger.info("[FLOW SEND] Enviando mensagem: %s", content)
    try:
        response = send_whatsapp_message(tenant, phone, content)
        print(f"[FLOW SEND RESULT] {response}")
    except WhatsAppConfigError as error:
        print(f"[FLOW ERROR] {error}")
        logger.warning("[FLOW SEND] Configuração WhatsApp ausente para tenant_id=%s", tenant.id)
    except Exception as error:
        print(f"[FLOW ERROR] {error}")
        logger.exception("[FLOW SEND] Falha inesperada ao enviar mensagem no flow")

def process_flow_engine(
    db: Session,
    tenant_id: uuid.UUID,
    phone: str,
    message_text: str = "",
    force_node: uuid.UUID | None = None,
) -> str | None:
    normalized_phone = normalize_phone(phone)
    conversation = db.execute(
        select(Conversation)
        .where(Conversation.tenant_id == tenant_id, Conversation.phone_number == normalized_phone)
        .order_by(desc(Conversation.updated_at), desc(Conversation.id))
    ).scalars().first()
    if not conversation:
        logger.info("Flow ignorado: conversa não encontrada tenant_id=%s phone=%s", tenant_id, normalized_phone)
        return None

    flow = _get_or_create_visual_flow(db=db, tenant_id=conversation.tenant_id)

    if force_node:
        _set_flow_mode(db=db, conversation=conversation, flow_id=flow.id, node_id=force_node)
        logger.info(
            "Flow retomado após delay conversation_id=%s force_node=%s",
            conversation.id,
            force_node,
        )
    elif not conversation.current_node_id:
        start_node = _get_start_node(db=db, flow_id=flow.id, tenant_id=conversation.tenant_id)
        if not start_node:
            return None

        _set_flow_mode(db=db, conversation=conversation, flow_id=flow.id, node_id=start_node.id)

    if conversation.mode == "flow" and conversation.current_node_id is None:
        logger.warning(
            "Flow inconsistente sem node_id, resetando para bot conversation_id=%s",
            conversation.id,
        )
        _reset_to_bot_mode(db=db, conversation=conversation, reason="current_node_none")
        return None

    if conversation.mode == "flow":
        _keep_flow_mode(conversation)

    tenant = db.execute(select(Tenant).where(Tenant.id == conversation.tenant_id)).scalars().first()
    if not tenant:
        logger.warning("[FLOW SEND] Tenant não encontrado para conversation_id=%s", conversation.id)
        return None

    conversation_phone = getattr(conversation, "phone", None) or conversation.phone_number

    node = _get_node(db=db, node_id=conversation.current_node_id, tenant_id=conversation.tenant_id)
    if not node:
        _reset_to_bot_mode(db=db, conversation=conversation, reason="flow_error_node_not_found")
        return None

    msg = _normalize_text(message_text)
    collected_messages: list[str] = []

    for _ in range(MAX_AUTO_STEPS):
        node_data = _extract_node_data(node)
        node_type = node.type
        if node_type.endswith("Node"):
            node_type = node_type[:-4]
        print(f"[FLOW DEBUG] node.type={node.type}")
        print(f"[FLOW DEBUG] node.data={getattr(node, 'data', None) or node_data}")
        logger.info("Node executado conversation_id=%s node_id=%s node_type=%s", conversation.id, node.id, node_type)

        edges = _get_edges(db=db, flow_id=node.flow_id, source=node.id)

        if node_type in {"message", "text", "msg", "start"}:
            metadata = node_data.get("metadata") if isinstance(node_data.get("metadata"), dict) else {}
            text = (node_data.get("text") or node_data.get("content") or metadata.get("text") or "").strip()
            if node_type in {"message", "text", "msg"}:
                if not text:
                    print("[FLOW ERROR] texto vazio no node")
                    return None
                _send_flow_whatsapp_message(tenant=tenant, phone=conversation_phone, text=text)
            elif text:
                collected_messages.append(text)
            node = _advance_to_edge_target(db=db, conversation=conversation, edge=_pick_default_edge(edges))
            if not node:
                break
            continue

        if node_type in {"choice", "question"}:
            expected_options = []
            buttons = node_data.get("buttons") if isinstance(node_data.get("buttons"), list) else []
            for button in buttons:
                if isinstance(button, dict) and button.get("label"):
                    expected_options.append(_normalize_text(str(button["label"])))

            edge_labels = [
                _normalize_text(edge.condition)
                for edge in edges
                if edge.condition and _normalize_text(edge.condition)
            ]
            options = expected_options or edge_labels

            if not msg:
                text = (node_data.get("text") or node_data.get("content") or "").strip()
                if not text:
                    text = _render_choice_prompt(node_data=node_data, edges=edges).strip()

                buttons = node_data.get("buttons") if isinstance(node_data.get("buttons"), list) else []

                if text:
                    if buttons and len(buttons) <= 3:
                        try:
                            send_whatsapp_interactive_buttons(
                                tenant=tenant,
                                phone=conversation_phone,
                                body_text=text,
                                buttons=buttons,
                            )
                            print(f"[FLOW BUTTON SEND] Botões enviados: {[b.get('label') for b in buttons]}")
                        except Exception as btn_err:
                            print(f"[FLOW BUTTON ERROR] {btn_err}")
                            _send_flow_whatsapp_message(tenant=tenant, phone=conversation_phone, text=text)
                    else:
                        _send_flow_whatsapp_message(tenant=tenant, phone=conversation_phone, text=text)
                else:
                    print("[FLOW ERROR] node choice sem texto")

                conversation.current_node_id = node.id
                db.commit()
                db.refresh(conversation)
                break

            selected_edge = None
            for edge in edges:
                condition = _normalize_text(edge.condition)
                if not condition:
                    continue
                # match exato (handleId do botão) ou por substring
                if condition == msg or condition in msg or msg in condition:
                    selected_edge = edge
                    break

            if not selected_edge and options:
                text = (node_data.get("text") or node_data.get("content") or "").strip()
                if not text:
                    text = _render_choice_prompt(node_data=node_data, edges=edges).strip()
                if text:
                    _send_flow_whatsapp_message(tenant=tenant, phone=conversation_phone, text=text)
                else:
                    print("[FLOW ERROR] node choice sem texto")
                break

            node = _advance_to_edge_target(db=db, conversation=conversation, edge=selected_edge or _pick_default_edge(edges))
            if not node:
                break
            continue

        if node_type == "condition":
            condition_text = _normalize_text(str(node_data.get("condition") or node_data.get("content") or ""))
            result = bool(condition_text and condition_text in msg)

            selected_edge = None
            for edge in edges:
                edge_condition = _normalize_text(edge.condition)
                if result and edge_condition in {"true", "sim", "yes"}:
                    selected_edge = edge
                    break
                if (not result) and edge_condition in {"false", "nao", "não", "no"}:
                    selected_edge = edge
                    break

            node = _advance_to_edge_target(db=db, conversation=conversation, edge=selected_edge or _pick_default_edge(edges))
            if not node:
                break
            continue

        if node_type == "delay":
            delay_value = str(node_data.get("content") or "").strip()
            try:
                delay_seconds = int(delay_value)
            except ValueError:
                delay_seconds = 0

            next_edge = _pick_default_edge(edges)
            if not next_edge:
                logger.info("Delay sem próxima aresta conversation_id=%s node_id=%s", conversation.id, node.id)
                _reset_to_bot_mode(db=db, conversation=conversation, reason="flow_finished_delay_without_next")
                break

            enqueue_delay(
                tenant_id=conversation.tenant_id,
                phone=conversation.phone_number,
                next_node_id=next_edge.target,
                seconds=delay_seconds,
            )
            conversation.current_node_id = next_edge.target
            _keep_flow_mode(conversation)
            break

        if node_type == "action":
            action_name = str(node_data.get("action") or "").strip()
            content = str(node_data.get("content") or "").strip()
            if content:
                collected_messages.append(content)
            elif action_name:
                collected_messages.append(f"⚙️ Ação executada: {action_name}")

            node = _advance_to_edge_target(db=db, conversation=conversation, edge=_pick_default_edge(edges))
            if not node:
                break
            continue

        content = (node_data.get("content") or "").strip()
        if content:
            collected_messages.append(content)
        node = _advance_to_edge_target(db=db, conversation=conversation, edge=_pick_default_edge(edges))
        if not node:
            break

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
        content="Você quer vendas, suporte ou atendimento?",
        metadata_json={
            "isStart": True,
            "label": "início",
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
        content="Perfeito, vamos seguir por vendas 🚀",
        metadata_json={"label": "vendas"},
        position_x=420,
        position_y=20,
    )
    suporte = FlowNode(
        flow_id=flow.id,
        tenant_id=tenant_id,
        type="message",
        content="Perfeito, vamos seguir por suporte 🛟",
        metadata_json={"label": "suporte"},
        position_x=420,
        position_y=140,
    )
    atendimento = FlowNode(
        flow_id=flow.id,
        tenant_id=tenant_id,
        type="message",
        content="Perfeito, vamos seguir por atendimento 💬",
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

        node_type = item.get("type") or "message"

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
        # Remove string vazia
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
        raise ValueError("Flow não encontrado para este tenant")
    return flow
