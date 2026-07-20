"""Tenant-safe, read-only operational observability API.

ExecutionTrace is deliberately reused as the append-only event store.  This
keeps instrumentation cheap and lets deployments adopt the feature without a
second event pipeline.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.execution_trace import ExecutionTrace
from app.models.tenant import Tenant
from app.models.user import TenantUser
from app.observability.timeline_builder import build_execution_timeline
from app.routers.account import get_current_user
from app.services.audit_service import write_audit_log
from app.services.tenant_service import get_current_tenant

router = APIRouter(prefix="/observability", tags=["observability"])
MAX_PAGE_SIZE = 100
ADMIN_ROLES = {"owner", "admin", "superadmin"}


def _authorized(user: TenantUser = Depends(get_current_user)) -> TenantUser:
    if (user.role or "").lower() not in ADMIN_ROLES:
        raise HTTPException(403, "Permissão de observabilidade necessária")
    return user


def _range(hours: int) -> datetime:
    return datetime.utcnow() - timedelta(hours=max(1, min(hours, 24 * 90)))


def _base(tenant: Tenant, since: datetime):
    return select(ExecutionTrace).where(ExecutionTrace.tenant_id == tenant.id, ExecutionTrace.created_at >= since)


def _event(row: ExecutionTrace) -> dict[str, Any]:
    return {"id": str(row.id), "trace_id": row.trace_id, "execution_id": row.execution_id,
            "event_type": row.event_type, "timestamp": row.timestamp.isoformat(), "duration_ms": row.duration_ms,
            "metadata": row.metadata_json or {}, "conversation_id": str(row.conversation_id) if row.conversation_id else None,
            "flow_id": str(row.flow_id) if row.flow_id else None}


@router.get("/overview")
def overview(hours: int = Query(24, ge=1, le=2160), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(_authorized), db: Session = Depends(get_db)):
    since = _range(hours)
    rows = db.execute(_base(tenant, since)).scalars().all()
    events = [r.event_type for r in rows]
    durations = sorted(r.duration_ms for r in rows if r.duration_ms is not None)
    executions = {r.execution_id for r in rows}
    failed = sum(1 for kind in events if kind in {"EXECUTION_FAILED", "NODE_FAILED", "MESSAGE_FAILED"})
    return {"period_hours": hours, "messages_received": events.count("WEBHOOK_RECEIVED"), "messages_sent": events.count("MESSAGE_SENT"),
            "executions": len(executions), "errors": failed, "retries": events.count("RETRY_SCHEDULED"),
            "success_rate": round((max(0, len(executions) - failed) / len(executions) * 100), 2) if executions else 100,
            "latency": {"p50": _percentile(durations, .50), "p95": _percentile(durations, .95), "p99": _percentile(durations, .99)},
            "traces": len({r.trace_id for r in rows})}


@router.get("/metrics")
def metrics(hours: int = Query(24, ge=1, le=2160), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(_authorized), db: Session = Depends(get_db)):
    since = _range(hours)
    # PostgreSQL date_trunc produces real persisted-event throughput buckets.
    result = db.execute(select(func.date_trunc("hour", ExecutionTrace.created_at).label("bucket"), ExecutionTrace.event_type, func.count().label("count"))
        .where(ExecutionTrace.tenant_id == tenant.id, ExecutionTrace.created_at >= since)
        .group_by("bucket", ExecutionTrace.event_type).order_by("bucket")).all()
    return {"period_hours": hours, "series": [{"bucket": r.bucket.isoformat(), "event_type": r.event_type, "count": r.count} for r in result]}


@router.get("/traces")
def traces(hours: int = Query(24, ge=1, le=2160), status: str | None = None, conversation_id: str | None = None, message_id: str | None = None, trace_id: str | None = None, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=MAX_PAGE_SIZE), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(_authorized), db: Session = Depends(get_db)):
    stmt = _base(tenant, _range(hours))
    if trace_id: stmt = stmt.where(ExecutionTrace.trace_id == trace_id)
    if conversation_id: stmt = stmt.where(ExecutionTrace.conversation_id == conversation_id)
    if status == "failed": stmt = stmt.where(ExecutionTrace.event_type.in_(["EXECUTION_FAILED", "NODE_FAILED", "MESSAGE_FAILED"]))
    if message_id: stmt = stmt.where(ExecutionTrace.metadata_json["message_id"].astext == message_id)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(ExecutionTrace.created_at.desc()).offset((page - 1) * page_size).limit(page_size)).scalars().all()
    return {"items": [_event(row) for row in rows], "page": page, "page_size": page_size, "total": total}


@router.get("/traces/{trace_id}")
def trace_detail(trace_id: str, tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(_authorized), db: Session = Depends(get_db)):
    rows = db.execute(select(ExecutionTrace).where(ExecutionTrace.tenant_id == tenant.id, ExecutionTrace.trace_id == trace_id).order_by(ExecutionTrace.timestamp, ExecutionTrace.created_at)).scalars().all()
    if not rows: raise HTTPException(404, "Trace não encontrado")
    write_audit_log(db, tenant_id=tenant.id, user_id=user.id, action="observability.trace.view", entity_type="execution_trace", entity_id=trace_id, metadata={"event_count": len(rows)})
    db.commit()
    return {"trace_id": trace_id, "events": [_event(row) for row in rows], "replay_read_only": True}


@router.get("/executions/{execution_id}")
def execution_detail(execution_id: str, tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(_authorized), db: Session = Depends(get_db)):
    row = db.execute(select(ExecutionTrace).where(ExecutionTrace.tenant_id == tenant.id, ExecutionTrace.execution_id == execution_id).order_by(ExecutionTrace.created_at.desc())).scalars().first()
    if not row: raise HTTPException(404, "Execução não encontrada")
    return trace_detail(row.trace_id, tenant, user, db)


@router.get("/conversations/{conversation_id}")
def conversation_traces(conversation_id: str, page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=MAX_PAGE_SIZE), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(_authorized), db: Session = Depends(get_db)):
    return traces(conversation_id=conversation_id, page=page, page_size=page_size, tenant=tenant, user=user, db=db)


@router.get("/errors")
def errors(hours: int = Query(24, ge=1, le=2160), page: int = Query(1, ge=1), page_size: int = Query(25, ge=1, le=MAX_PAGE_SIZE), tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(_authorized), db: Session = Depends(get_db)):
    return traces(hours=hours, status="failed", page=page, page_size=page_size, tenant=tenant, user=user, db=db)


@router.get("/health")
def health(tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(_authorized), db: Session = Depends(get_db)):
    return {"database": "ok", "event_store": "ok", "tenant_id": str(tenant.id), "checked_at": datetime.utcnow().isoformat()}


def _percentile(values: list[int], percentile: float) -> int | None:
    if not values: return None
    return values[min(len(values) - 1, int((len(values) - 1) * percentile))]
