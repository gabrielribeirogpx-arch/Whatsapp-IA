from __future__ import annotations

import logging
import re
import time
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.services.llm_service import generate_answer_for_tenant

logger = logging.getLogger(__name__)

_CONTEXT_REFERENCE_TERMS = (
    "isso aí", "o mesmo", "a mesma", "qual deles", "qual delas", "como assim", "qual valor", "qual prazo",
    "isso", "esse", "esses", "essas", "aquele", "aquela", "aqueles", "elas", "eles", "ele", "ela", "também",
    "e o", "e a", "e os", "e as", "quanto",
)
_GREETING_TERMS = {"oi", "olá", "ola", "bom dia", "boa tarde", "boa noite", "tudo bem"}
_CACHE_TTL_SECONDS = 60


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip()).strip()


def _normalize(value: str) -> str:
    return clean_text(value).lower()


def is_greeting(question: str) -> bool:
    normalized = _normalize(question).strip(" ?!.…")
    return normalized in _GREETING_TERMS


def contains_context_reference(question: str) -> bool:
    normalized = _normalize(question)
    if not normalized or is_greeting(normalized):
        return False
    tokens = set(re.findall(r"\w+", normalized))
    for term in _CONTEXT_REFERENCE_TERMS:
        if " " in term:
            if term in normalized:
                return True
        elif term in tokens:
            return True
    return False


def _history_message_count(conversation_history: Any) -> int:
    if not conversation_history:
        return 0
    if isinstance(conversation_history, (list, tuple)):
        return len(conversation_history)
    text = str(conversation_history)
    return len([line for line in text.splitlines() if line.strip()]) or (1 if text.strip() else 0)


def _cache_key(tenant_id: Any, current_question: str) -> str:
    return f"{tenant_id}:{clean_text(current_question).lower()}"


def get_cached_standalone(session_context: dict[str, Any] | None, *, tenant_id: Any, current_question: str, now: float | None = None) -> dict[str, Any] | None:
    if not isinstance(session_context, dict):
        return None
    cached = session_context.get("last_standalone_question")
    if not isinstance(cached, dict):
        return None
    if cached.get("key") != _cache_key(tenant_id, current_question):
        return None
    timestamp = float(cached.get("timestamp") or 0)
    if (now or time.time()) - timestamp > _CACHE_TTL_SECONDS:
        return None
    standalone = clean_text(str(cached.get("standalone_question") or ""))
    if not standalone:
        return None
    return {"standalone_question": standalone, "used_history": bool(cached.get("used_history")), "cache_hit": True}


def store_cached_standalone(session_context: dict[str, Any], *, tenant_id: Any, current_question: str, result: dict[str, Any], now: float | None = None) -> None:
    session_context["last_standalone_question"] = {
        "key": _cache_key(tenant_id, current_question),
        "standalone_question": clean_text(str(result.get("standalone_question") or current_question)),
        "used_history": bool(result.get("used_history")),
        "timestamp": now or time.time(),
    }


def generate_standalone_question(
    db: Session,
    tenant_id: uuid.UUID,
    current_question: str,
    conversation_history: str | None,
    assistant_instruction: str | None = None,
) -> dict[str, Any]:
    question = clean_text(current_question)
    if not question or is_greeting(question) or not contains_context_reference(question):
        return {"standalone_question": question, "used_history": False}
    if not clean_text(str(conversation_history or "")):
        return {"standalone_question": question, "used_history": False}
    try:
        system_prompt = (
            "Reescreva a pergunta abaixo para que possa ser entendida isoladamente.\n\n"
            "Use o histórico apenas para resolver referências.\n\n"
            "Não responda a pergunta.\n\n"
            "Não invente informações.\n\n"
            "Retorne somente a pergunta reescrita."
        )
        user_prompt = "\n\n".join(
            [
                f"Instrução do assistente (se útil): {(assistant_instruction or '')[:500]}",
                f"Histórico recente:\n{str(conversation_history or '')[:2500]}",
                f"Pergunta atual:\n{question[:500]}",
            ]
        )
        rewritten = clean_text(generate_answer_for_tenant(db, tenant_id, [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}], options={"temperature": 0, "max_tokens": 120}))
        rewritten = rewritten.strip('"“”')[:500]
        logger.info("[CONTEXTUAL QUERY] tenant=%s used_history=true rewritten=%s history_messages=%s", tenant_id, bool(rewritten and rewritten != question), _history_message_count(conversation_history))
        return {"standalone_question": rewritten or question, "used_history": bool(rewritten)}
    except Exception:
        logger.info("[CONTEXTUAL QUERY] tenant=%s used_history=false rewritten=false history_messages=%s failed=true", tenant_id, _history_message_count(conversation_history))
        return {"standalone_question": question, "used_history": False}
