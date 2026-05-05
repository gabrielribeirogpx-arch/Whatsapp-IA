from __future__ import annotations

import unicodedata
import logging
import re
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.models import Conversation, Flow, FlowStep, FlowVersion, Message
from app.services.flow_engine_service import get_flow_graph, save_flow_graph
from app.services.cache_service import invalidate_tenant_and_flow_cache

DEFAULT_FLOW_NAME = "default_visual"
DEFAULT_START_STEP = "inicio"

DEFAULT_FLOW_STEPS: list[dict[str, Any]] = [
    {
        "step_key": "inicio",
        "message": "Pra te ajudar melhor: vendas, suporte ou atendimento?",
        "expected_inputs": ["vendas", "suporte", "atendimento"],
        "next_step_map": {
            "vendas": "tipo_atendimento",
            "suporte": "suporte_step",
            "atendimento": "atendimento_step",
        },
    },
    {
        "step_key": "tipo_atendimento",
        "message": "Você prefere manual ou automático?",
        "expected_inputs": ["manual", "automatico"],
        "next_step_map": {
            "manual": "oferta_manual",
            "automatico": "oferta_auto",
        },
    },
    {
        "step_key": "oferta_manual",
        "message": "Perfeito. Começar manual é ótimo. Quer ver os planos?",
        "expected_inputs": ["sim", "quero"],
        "next_step_map": {"sim": "planos", "quero": "planos"},
    },
    {
        "step_key": "oferta_auto",
        "message": "Excelente. O automático acelera seu atendimento. Quer ver os planos?",
        "expected_inputs": ["sim", "quero"],
        "next_step_map": {"sim": "planos", "quero": "planos"},
    },
    {
        "step_key": "planos",
        "message": "Temos Básico, Essencial e PRO. Qual você quer?",
        "expected_inputs": ["basico", "essencial", "pro"],
        "next_step_map": {
            "basico": "fechamento",
            "essencial": "fechamento",
            "pro": "fechamento",
        },
    },
    {
        "step_key": "fechamento",
        "message": "Posso ativar agora pra você 🚀 Quer começar?",
        "expected_inputs": ["sim", "quero"],
        "next_step_map": None,
    },
    {
        "step_key": "suporte_step",
        "message": "Perfeito! Me conta em uma frase o que você precisa de suporte.",
        "expected_inputs": None,
        "next_step_map": None,
    },
    {
        "step_key": "atendimento_step",
        "message": "Claro! Me diz como prefere que o atendimento aconteça hoje.",
        "expected_inputs": None,
        "next_step_map": None,
    },
]
logger = logging.getLogger(__name__)


class FlowService:
    def __init__(self, db: Session):
        self.db = db

    def create_flow(self, tenant_id, data: dict[str, Any]) -> Flow:
        return create_flow(db=self.db, tenant_id=tenant_id, data=data)

    def create_version(self, flow: Flow, tenant_id, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> FlowVersion:
        with self.db.begin_nested():
            self.db.execute(select(Flow.id).where(Flow.id == flow.id).with_for_update())
            last_version = self.db.execute(
                select(FlowVersion.version)
                .where(FlowVersion.flow_id == flow.id)
                .order_by(FlowVersion.version.desc())
                .limit(1)
                .with_for_update()
            ).scalar()
            next_version = (last_version or 0) + 1
            version = FlowVersion(
                flow_id=flow.id,
                tenant_id=tenant_id,
                version=next_version,
                snapshot={"nodes": nodes, "edges": edges},
                nodes=nodes,
                edges=edges,
                is_active=False,
                is_published=False,
            )
            self.db.add(version)
            self.db.flush()
            flow.current_version_id = version.id
            flow.version = version.version
            # compatibilidade temporária para frontend legado
            flow.nodes_json = nodes
            flow.edges_json = edges
            flow.nodes = nodes
            flow.edges = edges
            self.db.add(flow)
            self.db.flush()
            logger.info(
                "[FLOW VERSION CREATE] tenant_id=%s flow_id=%s version_id=%s request_id=%s",
                tenant_id,
                flow.id,
                version.id,
                None,
            )
            return version

    def publish_version(self, flow: Flow, flow_version: FlowVersion) -> None:
        self.db.query(FlowVersion).filter(FlowVersion.flow_id == flow.id).update({FlowVersion.is_published: False}, synchronize_session=False)
        self.db.query(FlowVersion).filter(FlowVersion.id == flow_version.id).update({FlowVersion.is_published: True}, synchronize_session=False)
        flow.published_version_id = flow_version.id
        self.db.add(flow)
        logger.info(
            "[FLOW PUBLISH] tenant_id=%s flow_id=%s version_id=%s request_id=%s",
            flow.tenant_id,
            flow.id,
            flow_version.id,
            None,
        )
        invalidate_tenant_and_flow_cache(str(flow.tenant_id))

    def get_flow_with_version(self, flow: Flow) -> dict[str, Any]:
        active_version = flow.current_version
        nodes = active_version.nodes if active_version and isinstance(active_version.nodes, list) else []
        edges = active_version.edges if active_version and isinstance(active_version.edges, list) else []
        version = active_version.version if active_version else (flow.version or 1)
        return {"flow": flow, "nodes": nodes, "edges": edges, "version": version}

    def delete_flow_soft(self, flow: Flow) -> None:
        flow.deleted_at = datetime.utcnow()
        self.db.add(flow)


def normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    without_punctuation = re.sub(r"[^\w\s]", " ", without_accents.lower())
    return " ".join(without_punctuation.split())


def _normalize_text(value: str | None) -> str:
    return normalize_text(value)


def _flow_seed_exists(db: Session, flow_id) -> bool:
    first_step = db.execute(
        select(FlowStep.id).where(FlowStep.flow_id == flow_id, FlowStep.step_key == DEFAULT_START_STEP).limit(1)
    ).scalar_one_or_none()
    return first_step is not None


def _seed_default_steps(db: Session, flow: Flow) -> None:
    if _flow_seed_exists(db=db, flow_id=flow.id):
        return

    for step_data in DEFAULT_FLOW_STEPS:
        db.add(
            FlowStep(
                flow_id=flow.id,
                step_key=step_data["step_key"],
                message=step_data["message"],
                expected_inputs=step_data.get("expected_inputs"),
                next_step_map=step_data.get("next_step_map"),
            )
        )
    db.flush()


def _get_or_create_default_flow(db: Session, tenant_id) -> Flow:
    flow = db.execute(
        select(Flow)
        .where(Flow.tenant_id == tenant_id, Flow.name == DEFAULT_FLOW_NAME, Flow.deleted_at.is_(None), Flow.is_deleted.is_(False))
        .order_by(Flow.created_at.asc(), Flow.id.asc())
    ).scalars().first()
    if not flow:
        flow = Flow(tenant_id=tenant_id, name=DEFAULT_FLOW_NAME)
        db.add(flow)
        db.flush()
    _seed_default_steps(db=db, flow=flow)
    return flow


def _get_step(db: Session, flow_id, step_key: str) -> FlowStep | None:
    return db.execute(
        select(FlowStep)
        .where(FlowStep.flow_id == flow_id, FlowStep.step_key == step_key)
        .order_by(FlowStep.created_at.asc(), FlowStep.id.asc())
    ).scalars().first()


def _split_trigger_keywords(trigger_value: str | None) -> list[str]:
    if not trigger_value:
        return []
    return [_normalize_text(item) for item in trigger_value.split(",") if _normalize_text(item)]


def _tokenize_text(value: str | None) -> set[str]:
    normalized = normalize_text(value)
    return {token for token in normalized.split() if token}


def _split_csv_words(value: str | None) -> list[str]:
    if not value:
        return []
    return [normalize_text(item) for item in value.split(",") if normalize_text(item)]


def score_flow(flow: Flow, message_text: str) -> int:
    normalized_message = normalize_text(message_text)
    message_tokens = _tokenize_text(message_text)
    score = 0

    keywords_source = flow.keywords if flow.keywords else flow.trigger_value
    keywords = _split_csv_words(keywords_source)
    stop_words = _split_csv_words(flow.stop_words)

    for keyword in keywords:
        if not keyword:
            continue
        keyword_tokens = _tokenize_text(keyword)
        if keyword_tokens and keyword_tokens.issubset(message_tokens):
            score += 10
        if normalized_message == keyword:
            score += 20

    for stop_word in stop_words:
        stop_tokens = _tokenize_text(stop_word)
        if stop_tokens and stop_tokens.issubset(message_tokens):
            score -= 20

    score += flow.priority or 0
    return score


def resolve_flow_for_message(db: Session, tenant_id, message_text: str, conversation: Conversation | None = None) -> Flow | None:
    if conversation and conversation.mode == "flow":
        logger.info("[FLOW SKIP MODE] conversation_id=%s mode=flow", conversation.id)
        return None

    active_flows = db.execute(
        select(Flow)
        .where(Flow.tenant_id == tenant_id, Flow.is_active.is_(True), Flow.deleted_at.is_(None), Flow.is_deleted.is_(False))
        .order_by(Flow.created_at.asc(), Flow.id.asc())
    ).scalars().all()

    default_flow: Flow | None = None
    scored_flows: list[tuple[int, Flow]] = []
    for flow in active_flows:
        trigger_type = _normalize_text(flow.trigger_type)
        if trigger_type == "default" and default_flow is None:
            default_flow = flow
            continue

        if trigger_type != "keyword":
            continue

        keywords = _split_csv_words(flow.keywords) if flow.keywords else _split_trigger_keywords(flow.trigger_value)
        if not keywords:
            continue

        score = score_flow(flow, message_text)
        logger.info("[FLOW SCORE] flow_id=%s score=%s", flow.id, score)
        scored_flows.append((score, flow))

    scored_flows.sort(key=lambda item: item[0], reverse=True)
    if scored_flows:
        winner_score, winner_flow = scored_flows[0]
        if winner_score > 0:
            logger.info("[FLOW WINNER] flow_id=%s score=%s", winner_flow.id, winner_score)
            return winner_flow

    if default_flow:
        logger.info("[FLOW RESOLVED] tenant=%s flow_id=%s reason=default", tenant_id, default_flow.id)
        return default_flow

    logger.info("[FLOW NO MATCH] tenant=%s", tenant_id)
    return None


def process_flow(db: Session, conversation: Conversation, message_text: str) -> str | None:
    step = conversation.current_step
    if not step or not conversation.current_flow:
        return None

    step_data = _get_step(db=db, flow_id=conversation.current_flow, step_key=step)
    if not step_data:
        return None

    expected_inputs = list(step_data.expected_inputs or [])
    next_step_map = dict(step_data.next_step_map or {})
    if not expected_inputs:
        return None

    msg = _normalize_text(message_text)
    for key in expected_inputs:
        normalized_key = _normalize_text(key)
        if normalized_key and normalized_key in msg:
            next_step = next_step_map.get(key) or next_step_map.get(normalized_key)
            if next_step:
                conversation.current_step = next_step
                next_data = _get_step(db=db, flow_id=conversation.current_flow, step_key=next_step)
                if next_data:
                    return next_data.message
            return None

    options = ", ".join(expected_inputs)
    return f"Não entendi 🤔 responde pra mim uma dessas opções: {options}"


def handle_flow(db: Session, conversation: Conversation, message: Message) -> str | None:
    default_flow = _get_or_create_default_flow(db=db, tenant_id=conversation.tenant_id)
    if not conversation.current_step:
        conversation.current_flow = default_flow.id
        conversation.current_step = DEFAULT_START_STEP
        first_step = _get_step(db=db, flow_id=default_flow.id, step_key=DEFAULT_START_STEP)
        return first_step.message if first_step else None

    if not conversation.current_flow:
        conversation.current_flow = default_flow.id

    return process_flow(db=db, conversation=conversation, message_text=message.text or "")


def create_flow(db: Session, tenant_id, data: dict[str, Any]) -> Flow:
    has_active_flow = db.execute(
        select(Flow.id).where(
            Flow.tenant_id == tenant_id,
            Flow.is_active.is_(True),
        ).limit(1)
    ).scalar_one_or_none() is not None

    requested_active = data.get("is_active")
    should_activate = bool(requested_active) if requested_active is not None else not has_active_flow

    if should_activate:
        db.execute(
            update(Flow)
            .where(Flow.tenant_id == tenant_id)
            .values(is_active=False)
        )

    flow = Flow(
        tenant_id=tenant_id,
        name=data["name"],
        description=data.get("description"),
        is_active=should_activate,
        trigger_type=data.get("trigger_type", "default"),
        trigger_value=data.get("trigger_value"),
        keywords=data.get("keywords"),
        stop_words=data.get("stop_words"),
        priority=data.get("priority", 0),
        version=data.get("version", 1),
        nodes=data.get("nodes", []),
        edges=data.get("edges", []),
    )
    db.add(flow)
    db.flush()
    logger.info(
        "[FLOW CREATE] tenant_id=%s flow_id=%s version_id=%s request_id=%s",
        tenant_id,
        flow.id,
        None,
        data.get("request_id"),
    )
    return flow


def get_flows(db: Session, tenant_id) -> list[Flow]:
    return db.execute(
        select(Flow)
        .where(Flow.tenant_id == tenant_id, Flow.deleted_at.is_(None), Flow.is_deleted.is_(False))
        .order_by(Flow.created_at.desc(), Flow.id.desc())
    ).scalars().all()


def get_flow(db: Session, flow_id, tenant_id) -> Flow | None:
    return db.execute(
        select(Flow).where(Flow.id == flow_id, Flow.tenant_id == tenant_id, Flow.deleted_at.is_(None), Flow.is_deleted.is_(False))
    ).scalars().first()


def update_flow(db: Session, flow_id, tenant_id, data: dict[str, Any]) -> Flow | None:
    flow = get_flow(db=db, flow_id=flow_id, tenant_id=tenant_id)
    if not flow:
        return None

    if "name" in data:
        flow.name = data["name"]
    if "description" in data:
        flow.description = data["description"]
    if "is_active" in data:
        flow.is_active = data["is_active"]
    if "trigger_type" in data:
        flow.trigger_type = data["trigger_type"]
    if "trigger_value" in data:
        flow.trigger_value = data["trigger_value"]
    if "keywords" in data:
        flow.keywords = data["keywords"]
    if "stop_words" in data:
        flow.stop_words = data["stop_words"]
    if "priority" in data:
        flow.priority = data["priority"]
    if "version" in data:
        flow.version = data["version"]
    if "nodes" in data or "edges" in data:
        raise ValueError("Atualização direta de nodes/edges em flows não é permitida; crie uma nova flow_version.")

    db.add(flow)
    db.flush()
    logger.info("[FLOW UPDATED] flow_id=%s tenant_id=%s", flow.id, tenant_id)
    invalidate_tenant_and_flow_cache(str(tenant_id))
    return flow


def delete_flow(db: Session, flow_id, tenant_id) -> bool:
    flow = get_flow(db=db, flow_id=flow_id, tenant_id=tenant_id)
    if not flow:
        return False

    FlowService(db).delete_flow_soft(flow)
    db.flush()
    logger.info(
        "[FLOW DELETE] tenant_id=%s flow_id=%s version_id=%s request_id=%s",
        tenant_id,
        flow_id,
        None,
        None,
    )
    return True


def duplicate_flow(db: Session, flow_id, tenant_id) -> Flow | None:
    source_flow = get_flow(db=db, flow_id=flow_id, tenant_id=tenant_id)
    if not source_flow:
        return None

    duplicated_flow = create_flow(
        db=db,
        tenant_id=tenant_id,
        data={
            "name": f"{source_flow.name} (cópia)",
            "description": source_flow.description,
            "is_active": source_flow.is_active,
            "trigger_type": source_flow.trigger_type,
            "trigger_value": source_flow.trigger_value,
            "keywords": source_flow.keywords,
            "stop_words": source_flow.stop_words,
            "priority": source_flow.priority,
            "version": source_flow.version,
        },
    )

    source_graph = get_flow_graph(db=db, tenant_id=tenant_id, flow_id=str(source_flow.id))
    save_flow_graph(
        db=db,
        tenant_id=tenant_id,
        flow_id=str(duplicated_flow.id),
        nodes=source_graph.get("nodes") or [],
        edges=source_graph.get("edges") or [],
    )
    db.flush()
    logger.info(
        "[FLOW DUPLICATED] source_flow_id=%s duplicated_flow_id=%s tenant_id=%s",
        source_flow.id,
        duplicated_flow.id,
        tenant_id,
    )
    return duplicated_flow
