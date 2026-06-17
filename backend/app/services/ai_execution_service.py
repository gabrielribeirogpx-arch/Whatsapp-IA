from __future__ import annotations

import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.flow import FlowVersion
from app.models.flow_ai_execution import FlowAIExecution
from app.services.llm_service import _resolve_tenant_config

logger = logging.getLogger(__name__)
_SECRET_RE = re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization|bearer)\s*[:=]\s*[^\s,;]+")


def redact_text(value: Any, limit: int = 320) -> str | None:
    if value is None:
        return None
    text = _SECRET_RE.sub(r"\1=[REDACTED]", str(value)).strip()
    return text[:limit]


def safe_metadata(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            lk = str(key).lower()
            if any(s in lk for s in ("api_key", "apikey", "secret", "token", "authorization", "embedding", "vector", "content", "prompt")):
                continue
            result[str(key)] = safe_metadata(item)
        return result
    if isinstance(value, list):
        return [safe_metadata(item) for item in value[:50]]
    if isinstance(value, str):
        return redact_text(value, 500)
    return value


def resolve_ai_config(db: Session, tenant_id: uuid.UUID, options: dict[str, Any] | None = None) -> dict[str, str | None]:
    try:
        cfg = _resolve_tenant_config(db, tenant_id, options=options)
        return {"provider": str(cfg.get("provider") or ""), "model": str(cfg.get("chat_model") or cfg.get("model") or "")}
    except Exception:
        return {"provider": None, "model": (options or {}).get("chat_model") or (options or {}).get("model")}


def score_confidence(contexts: list[dict[str, Any]] | None, fallback: bool = False) -> float | None:
    if fallback:
        return 0.0
    if not contexts:
        return None
    try:
        return max(float(c.get("final_score") or c.get("score") or 0) for c in contexts)
    except Exception:
        return None


def get_flow_id(db: Session, snapshot: Any, session: Any) -> uuid.UUID | None:
    flow_id = getattr(snapshot, "flow_id", None) or getattr(session, "flow_id", None)
    if flow_id is None and hasattr(db, "get") and getattr(session, "flow_version_id", None):
        fv = db.get(FlowVersion, session.flow_version_id)
        flow_id = getattr(fv, "flow_id", None)
    return flow_id


def record_ai_execution(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID | None,
    session_id: uuid.UUID | None,
    flow_id: uuid.UUID | None,
    flow_version_id: uuid.UUID | None,
    node_id: str,
    node_type: str,
    provider: str | None,
    model: str | None,
    started_at: datetime,
    status: str,
    input_text: Any = None,
    output_text: Any = None,
    retrieval_mode: str | None = None,
    confidence: float | None = None,
    fallback_used: bool = False,
    metadata: dict[str, Any] | None = None,
) -> FlowAIExecution | None:
    finished_at = datetime.now(UTC).replace(tzinfo=None)
    start = started_at.replace(tzinfo=None) if started_at.tzinfo else started_at
    latency_ms = max(0, int((finished_at - start).total_seconds() * 1000))
    safe = safe_metadata(metadata or {})
    row = FlowAIExecution(
        tenant_id=tenant_id,
        conversation_id=conversation_id,
        session_id=session_id,
        flow_id=flow_id,
        flow_version_id=flow_version_id,
        node_id=node_id,
        node_type=node_type,
        provider=provider,
        model=model,
        started_at=start,
        finished_at=finished_at,
        latency_ms=latency_ms,
        status=status,
        input_size=len(str(input_text or "")),
        output_size=len(str(output_text or "")),
        retrieval_mode=retrieval_mode,
        confidence=confidence,
        fallback_used=bool(fallback_used),
        metadata_json=safe,
    )
    try:
        db.add(row)
        logger.info("[AI EXECUTION] tenant=%s flow=%s node=%s provider=%s model=%s latency=%s status=%s confidence=%s fallback=%s", tenant_id, flow_id, node_id, provider, model, latency_ms, status, confidence, fallback_used)
        return row
    except Exception:
        logger.debug("[AI EXECUTION] record skipped", exc_info=True)
        return None


def metrics(db: Session, tenant_id: uuid.UUID) -> dict[str, Any]:
    today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0, tzinfo=None)
    base = select(FlowAIExecution).where(FlowAIExecution.tenant_id == tenant_id)
    total_today = db.scalar(select(func.count()).select_from(FlowAIExecution).where(FlowAIExecution.tenant_id == tenant_id, FlowAIExecution.created_at >= today)) or 0
    avg_latency = db.scalar(select(func.avg(FlowAIExecution.latency_ms)).where(FlowAIExecution.tenant_id == tenant_id)) or 0
    total = db.scalar(select(func.count()).select_from(FlowAIExecution).where(FlowAIExecution.tenant_id == tenant_id)) or 0
    fallback = db.scalar(select(func.count()).select_from(FlowAIExecution).where(FlowAIExecution.tenant_id == tenant_id, FlowAIExecution.fallback_used.is_(True))) or 0
    avg_conf = db.scalar(select(func.avg(FlowAIExecution.confidence)).where(FlowAIExecution.tenant_id == tenant_id))
    def top(col):
        rows = db.execute(select(col, func.count()).where(FlowAIExecution.tenant_id == tenant_id, col.is_not(None)).group_by(col).order_by(func.count().desc()).limit(5)).all()
        return [{"name": r[0], "count": r[1]} for r in rows]
    return {"today": total_today, "avg_latency_ms": round(float(avg_latency), 1), "fallback_percent": round((fallback / total * 100), 1) if total else 0, "avg_confidence": round(float(avg_conf), 3) if avg_conf is not None else None, "top_providers": top(FlowAIExecution.provider), "top_models": top(FlowAIExecution.model)}
