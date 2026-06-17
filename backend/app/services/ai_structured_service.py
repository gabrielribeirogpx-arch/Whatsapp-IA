from __future__ import annotations

import json
import logging
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.services.llm_service import generate_answer_for_tenant

logger = logging.getLogger(__name__)

_JSON_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE | re.MULTILINE)
SUPPORTED_FIELD_TYPES = {"string", "number", "boolean", "date", "email", "phone", "cpf", "cnpj"}

class AIStructuredError(RuntimeError):
    pass


def _parse_json_only(raw: str) -> dict[str, Any]:
    text = _JSON_FENCE_RE.sub("", str(raw or "")).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise AIStructuredError("AI_STRUCTURED_INVALID_JSON")
        try:
            parsed = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise AIStructuredError("AI_STRUCTURED_INVALID_JSON") from exc
    if not isinstance(parsed, dict):
        raise AIStructuredError("AI_STRUCTURED_JSON_OBJECT_REQUIRED")
    return parsed


def _clean_categories(categories: list[Any]) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    for item in categories or []:
        value = str(item or "").strip()
        if value and value not in seen:
            cleaned.append(value)
            seen.add(value)
    return cleaned


def _coerce_confidence(value: Any) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(parsed, 1.0))


def classify_for_tenant(db: Session, tenant_id: uuid.UUID, input_text: str, categories: list[Any], instruction: str | None = None, options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = options or {}
    allowed = _clean_categories(categories)
    if not allowed:
        raise AIStructuredError("AI_CLASSIFICATION_CATEGORIES_REQUIRED")
    allow_other = opts.get("allow_other", True) is not False
    fallback = "outro" if allow_other else allowed[0]
    threshold = _coerce_confidence(opts.get("confidence_threshold", 0.6))
    category_list = allowed + (["outro"] if allow_other and "outro" not in allowed else [])
    system = (
        "Classifique a mensagem em uma das categorias permitidas. Retorne somente JSON válido. "
        "Não use markdown. Não use ```json. Não explique. reason deve ser curto. "
        "Formato obrigatório: {\"category\":\"...\",\"confidence\":0.0,\"reason\":\"curto\"}. "
        f"Categorias permitidas: {json.dumps(category_list, ensure_ascii=False)}. "
        f"Se não encaixar e permitido, use {fallback!r}."
    )
    if instruction:
        system += f"\nInstrução adicional: {instruction[:2000]}"
    logger.info("[AI STRUCTURED] classify tenant_id=%s categories_count=%s input_length=%s", tenant_id, len(category_list), len(str(input_text or "")))
    raw = generate_answer_for_tenant(db, tenant_id, [{"role": "system", "content": system}, {"role": "user", "content": str(input_text or "")[:12000]}], options={"temperature": 0, "max_tokens": 220})
    parsed = _parse_json_only(raw)
    category = str(parsed.get("category") or "").strip()
    confidence = _coerce_confidence(parsed.get("confidence"))
    if category not in category_list or confidence < threshold:
        category = fallback
    return {"category": category, "confidence": confidence, "reason": str(parsed.get("reason") or "")[:180]}


def extract_for_tenant(db: Session, tenant_id: uuid.UUID, input_text: str, fields: list[dict[str, Any]], instruction: str | None = None, conversation_history: str | None = None, options: dict[str, Any] | None = None) -> dict[str, Any]:
    clean_fields = []
    for field in fields or []:
        if not isinstance(field, dict):
            continue
        name = str(field.get("name") or "").strip()
        typ = str(field.get("type") or "string").strip().lower()
        if name and typ in SUPPORTED_FIELD_TYPES:
            clean_fields.append({"name": name, "type": typ, "description": str(field.get("description") or "")[:400]})
    if not clean_fields:
        raise AIStructuredError("AI_EXTRACTION_FIELDS_REQUIRED")
    system = (
        "Extraia os campos solicitados. Retorne somente JSON válido. Não use markdown. Não use ```json. "
        "Não explique. Se não souber, use null. Não inventar. "
        "Formato obrigatório: {\"data\":{...},\"missing_fields\":[...],\"confidence\":0.0}. "
        f"Campos: {json.dumps(clean_fields, ensure_ascii=False)}."
    )
    if instruction:
        system += f"\nInstrução adicional: {instruction[:2000]}"
    user = str(input_text or "")[:12000]
    if conversation_history:
        user = f"Histórico:\n{str(conversation_history)[:8000]}\n\nEntrada:\n{user}"
    logger.info("[AI STRUCTURED] extract tenant_id=%s fields_count=%s input_length=%s history=%s", tenant_id, len(clean_fields), len(str(input_text or "")), bool(conversation_history))
    raw = generate_answer_for_tenant(db, tenant_id, [{"role": "system", "content": system}, {"role": "user", "content": user}], options={"temperature": 0, "max_tokens": 700})
    parsed = _parse_json_only(raw)
    data = parsed.get("data") if isinstance(parsed.get("data"), dict) else {}
    names = [field["name"] for field in clean_fields]
    normalized = {name: data.get(name) for name in names}
    missing = [name for name in names if normalized.get(name) in (None, "")]
    parsed_missing = parsed.get("missing_fields")
    if isinstance(parsed_missing, list):
        missing = sorted(set(missing) | {str(x) for x in parsed_missing if str(x) in names})
    return {"data": normalized, "missing_fields": missing, "confidence": _coerce_confidence(parsed.get("confidence"))}
