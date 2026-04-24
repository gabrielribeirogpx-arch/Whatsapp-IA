from __future__ import annotations

import unicodedata
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Conversation, Flow, FlowStep, Message

DEFAULT_FLOW_NAME = "__default__"
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


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKD", value)
    without_accents = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return without_accents.lower().strip()


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
        .where(Flow.tenant_id == tenant_id, Flow.name == DEFAULT_FLOW_NAME)
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


def resolve_flow_for_message(db: Session, tenant_id, message_text: str) -> Flow | None:
    normalized_message = _normalize_text(message_text)
    active_flows = db.execute(
        select(Flow)
        .where(Flow.tenant_id == tenant_id, Flow.is_active.is_(True))
        .order_by(Flow.created_at.asc(), Flow.id.asc())
    ).scalars().all()

    default_flow: Flow | None = None
    for flow in active_flows:
        trigger_type = _normalize_text(flow.trigger_type)
        if trigger_type == "default" and default_flow is None:
            default_flow = flow
            continue

        if trigger_type != "keyword":
            continue

        keywords = _split_trigger_keywords(flow.trigger_value)
        if not keywords:
            continue

        if any(keyword in normalized_message for keyword in keywords):
            logger.info("[FLOW RESOLVED] tenant=%s flow_id=%s reason=keyword", tenant_id, flow.id)
            return flow

    if default_flow:
        logger.info("[FLOW RESOLVED] tenant=%s flow_id=%s reason=default", tenant_id, default_flow.id)
        return default_flow

    logger.info("[FLOW NOT FOUND] tenant=%s", tenant_id)
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
    flow = Flow(
        tenant_id=tenant_id,
        name=data["name"],
        description=data.get("description"),
        is_active=data.get("is_active", True),
        trigger_type=data.get("trigger_type", "default"),
        trigger_value=data.get("trigger_value"),
        version=data.get("version", 1),
    )
    db.add(flow)
    db.flush()
    logger.info("[FLOW CREATED] flow_id=%s tenant_id=%s", flow.id, tenant_id)
    return flow


def get_flows(db: Session, tenant_id) -> list[Flow]:
    return db.execute(
        select(Flow)
        .where(Flow.tenant_id == tenant_id)
        .order_by(Flow.created_at.desc(), Flow.id.desc())
    ).scalars().all()


def get_flow(db: Session, flow_id, tenant_id) -> Flow | None:
    return db.execute(
        select(Flow).where(Flow.id == flow_id, Flow.tenant_id == tenant_id)
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
    if "version" in data:
        flow.version = data["version"]

    db.add(flow)
    db.flush()
    logger.info("[FLOW UPDATED] flow_id=%s tenant_id=%s", flow.id, tenant_id)
    return flow


def delete_flow(db: Session, flow_id, tenant_id) -> bool:
    flow = get_flow(db=db, flow_id=flow_id, tenant_id=tenant_id)
    if not flow:
        return False

    db.delete(flow)
    db.flush()
    logger.info("[FLOW DELETED] flow_id=%s tenant_id=%s", flow_id, tenant_id)
    return True
