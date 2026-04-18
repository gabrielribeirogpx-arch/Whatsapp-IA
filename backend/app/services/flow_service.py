from __future__ import annotations

import unicodedata
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
