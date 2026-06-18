from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.services.context_builder_service import build_context
from app.services.llm_service import generate_answer_for_tenant
from app.services.execution_budget_service import ExecutionBudget, ExecutionBudgetExceeded

MAX_SUPERVISOR_DEPTH = 3
FALLBACK_MESSAGE = "Não consegui identificar o especialista adequado."


@dataclass(frozen=True)
class SupervisorDecision:
    selected_agent: str | None
    reason: str = ""
    fallback_used: bool = False
    latency_ms: int = 0
    raw_valid: bool = True


def _extract_json_object(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
        return value if isinstance(value, dict) else None
    except Exception:
        match = re.search(r"\{.*\}", text or "", flags=re.S)
        if not match:
            return None
        try:
            value = json.loads(match.group(0))
            return value if isinstance(value, dict) else None
        except Exception:
            return None


def _agent_label(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return str(data.get("agent_name") or data.get("name") or data.get("label") or node.get("label") or node.get("id") or "IA Agente")


def _agent_description(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return str(data.get("description") or data.get("instruction") or "")[:600]


def build_available_agents(snapshot: Any, supervisor_node_id: str, selected_ids: list[Any]) -> list[dict[str, str]]:
    node_by_id = getattr(snapshot, "node_by_id", {}) or {}
    agents: list[dict[str, str]] = []
    for raw_id in selected_ids:
        node_id = str(raw_id)
        node = node_by_id.get(node_id)
        if not isinstance(node, dict) or node_id == supervisor_node_id:
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        node_type = str(node.get("type") or data.get("type") or "").strip().lower()
        if node_type != "ai_agent":
            continue
        agents.append({"id": node_id, "name": _agent_label(node), "description": _agent_description(node)})
    return agents


def decide_supervisor_agent(
    db: Session,
    tenant_id,
    *,
    message: str,
    supervisor_prompt: str,
    agents: list[dict[str, str]],
    context_section: str,
    fallback_agent_id: str | None,
    options: dict[str, Any] | None = None,
    budget: ExecutionBudget | None = None,
) -> SupervisorDecision:
    started = time.monotonic()
    valid_ids = {agent["id"] for agent in agents}
    if not agents:
        return SupervisorDecision(None, "empty_agent_list", True, 0, False)
    fallback = fallback_agent_id if fallback_agent_id in valid_ids else None
    agent_lines = "\n".join(f"- id={a['id']} | nome={a['name']} | descrição={a.get('description','')}" for a in agents)
    system = (
        "Você é um Supervisor IA. Escolha exatamente UM agente especializado para atender a mensagem. "
        "Responda somente JSON válido no formato {\"selected_agent\":\"node_id\",\"reason\":\"resumo curto\"}. "
        "Não invente IDs e não execute atendimento."
    )
    user = f"""Prompt do supervisor:
{supervisor_prompt or 'Escolha o agente mais adequado.'}

Agentes disponíveis:
{agent_lines}

Contexto e memória:
{context_section[:6000]}

Mensagem do usuário:
{message}
"""
    try:
        if budget is not None:
            budget.consume_llm_call(prompt_tokens_estimate=(len(system) + len(user)) // 4, completion_tokens_estimate=180)
        raw = generate_answer_for_tenant(db, tenant_id, [{"role": "system", "content": system}, {"role": "user", "content": user}], options=options or {"temperature": 0, "max_tokens": 180})
        parsed = _extract_json_object(raw)
        selected = str((parsed or {}).get("selected_agent") or "")
        reason = str((parsed or {}).get("reason") or "")[:240]
        if selected in valid_ids:
            return SupervisorDecision(selected, reason, False, int((time.monotonic() - started) * 1000), True)
        return SupervisorDecision(fallback, "invalid_or_unknown_agent", True, int((time.monotonic() - started) * 1000), False)
    except ExecutionBudgetExceeded:
        return SupervisorDecision(None, "budget_exceeded", True, int((time.monotonic() - started) * 1000), False)
    except Exception:
        return SupervisorDecision(fallback, "selection_failed", True, int((time.monotonic() - started) * 1000), False)


def get_supervisor_context(db: Session, tenant_id, *, contact_id=None, conversation_id=None, session_id=None, current_query="", memory_max_messages=10, memory_max_chars=4000) -> dict[str, Any]:
    return build_context(
        db,
        tenant_id,
        contact_id=contact_id,
        conversation_id=conversation_id,
        session_id=session_id,
        current_query=current_query,
        include_short_memory=True,
        include_long_memory=True,
        include_rag_context=False,
        short_memory_options={"max_messages": memory_max_messages, "max_chars": memory_max_chars},
    )
