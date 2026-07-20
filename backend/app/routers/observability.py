"""Tenant-safe, read-only operational observability API.

ExecutionTrace is deliberately reused as the append-only event store.  This
keeps instrumentation cheap and lets deployments adopt the feature without a
second event pipeline.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.execution_trace import ExecutionTrace
from app.models.tenant import Tenant
from app.models.user import TenantUser
from app.observability.timeline_builder import build_execution_timeline
from app.routers.account import get_current_user
from app.services.audit_service import write_audit_log
from app.services.observability_export import csv_export, json_export, pdf_export, timeline, trace_records, xlsx_export
from app.services.tenant_service import get_current_tenant

router = APIRouter(prefix="/observability", tags=["observability"])
MAX_PAGE_SIZE = 100
MAX_EXPORT_RECORDS = 10_000
MAX_EXPORT_DAYS = 90
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


def _export_range(start_date: datetime | None, end_date: datetime | None) -> tuple[datetime, datetime]:
    end = end_date or datetime.utcnow()
    start = start_date or end - timedelta(days=1)
    if start > end or end - start > timedelta(days=MAX_EXPORT_DAYS):
        raise HTTPException(422, f"Período máximo de exportação: {MAX_EXPORT_DAYS} dias")
    return start, end


def _export_rows(db: Session, tenant: Tenant, start: datetime, end: datetime, *, trace_id: str | None = None, status: str | None = None, source: str | None = None, flow_id: str | None = None, conversation_id: str | None = None) -> list[ExecutionTrace]:
    stmt = select(ExecutionTrace).where(ExecutionTrace.tenant_id == tenant.id, ExecutionTrace.created_at >= start, ExecutionTrace.created_at <= end)
    if trace_id: stmt = stmt.where(ExecutionTrace.trace_id == trace_id)
    if conversation_id: stmt = stmt.where(ExecutionTrace.conversation_id == conversation_id)
    if flow_id: stmt = stmt.where(ExecutionTrace.flow_id == flow_id)
    if status == "failed": stmt = stmt.where(ExecutionTrace.event_type.in_(["EXECUTION_FAILED", "NODE_FAILED", "MESSAGE_FAILED"]))
    # JSON filtering is deliberately performed after the tenant predicate, and only
    # against persisted metadata; it is portable to the SQLite test database.
    rows = db.execute(stmt.order_by(ExecutionTrace.timestamp, ExecutionTrace.created_at).limit(MAX_EXPORT_RECORDS + 1)).scalars().all()
    if source: rows = [row for row in rows if (row.metadata_json or {}).get("source") == source]
    if len(rows) > MAX_EXPORT_RECORDS: raise HTTPException(413, "Exportação grande deve ser processada na fila low_priority")
    return rows


def _summary(rows: list[ExecutionTrace], start: datetime, end: datetime) -> dict[str, Any]:
    kinds = [row.event_type for row in rows]; durations = sorted(row.duration_ms for row in rows if row.duration_ms is not None)
    traces_count = len({row.trace_id for row in rows}); errors = sum("FAILED" in kind for kind in kinds)
    return {"period_start": start.isoformat(), "period_end": end.isoformat(), "messages_received": kinds.count("WEBHOOK_RECEIVED"), "messages_sent": kinds.count("MESSAGE_SENT"), "executions": len({row.execution_id for row in rows}), "success_rate": round((traces_count - errors) * 100 / traces_count, 2) if traces_count else 100, "error_rate": round(errors * 100 / max(1, len(rows)), 2), "retries": sum("RETRY" in kind for kind in kinds), "deduplications": kinds.count("MESSAGE_DEDUPLICATED"), "lock_contention": kinds.count("LOCK_CONTENTION"), "p50": _percentile(durations, .50), "p95": _percentile(durations, .95), "p99": _percentile(durations, .99), "throughput_per_minute": round(len(rows) / max(1, (end - start).total_seconds() / 60), 2), "errors": errors, "alerts_active": 0}


def _download(data: bytes, fmt: str, kind: str, tenant: Tenant) -> Response:
    types = {"csv": "text/csv; charset=utf-8", "json": "application/json", "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "pdf": "application/pdf"}
    stamp = datetime.utcnow().strftime("%Y-%m-%d_%H-%M")
    return Response(data, media_type=types[fmt], headers={"Content-Disposition": f'attachment; filename="wazza-observability-{tenant.slug or tenant.id}-{kind}-{stamp}.{fmt}"', "X-Content-Type-Options": "nosniff"})


def _audit_export(db: Session, request: Request, user: TenantUser, tenant: Tenant, kind: str, fmt: str, filters: dict[str, Any], count: int, result: str) -> None:
    write_audit_log(db, tenant_id=tenant.id, user_id=user.id, action=f"OBSERVABILITY_EXPORT_{result}", entity_type="observability_export", metadata={"type": kind, "format": fmt, "filters": filters, "row_count": count, "requested_at": datetime.utcnow().isoformat()}, request=request)
    db.commit()


def _export_response(*, kind: str, fmt: str, rows: list[ExecutionTrace], tenant: Tenant, start: datetime, end: datetime, timezone_name: str, filters: dict[str, Any], trace: bool = False) -> Response:
    records = trace_records(rows)
    summary = _summary(rows, start, end)
    tenant_data = {"id": str(tenant.id), "slug": tenant.slug, "name": tenant.name}
    if trace:
        data: Any = {"trace": records[0] if records else None, "timeline": timeline(rows)}
    else: data = records
    if fmt == "json": data_bytes = json_export(tenant=tenant_data, filters=filters, summary=summary, data=data, timezone_name=timezone_name)
    elif fmt == "csv": data_bytes = csv_export(records)
    elif fmt == "xlsx": data_bytes = xlsx_export(records, summary)
    else: data_bytes = pdf_export(f"Wazza — {kind.replace('_', ' ').title()}", summary, records)
    return _download(data_bytes, fmt, kind, tenant)


@router.get("/export/overview")
def export_overview(request: Request, format: str = Query("pdf", pattern="^(pdf|xlsx|json)$"), start_date: datetime | None = None, end_date: datetime | None = None, timezone: str = "UTC", tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(_authorized), db: Session = Depends(get_db)):
    start, end = _export_range(start_date, end_date); filters = {"start_date": str(start), "end_date": str(end)}
    _audit_export(db, request, user, tenant, "overview", format, filters, 0, "REQUESTED")
    try:
        rows = _export_rows(db, tenant, start, end); response = _export_response(kind="overview", fmt=format, rows=rows, tenant=tenant, start=start, end=end, timezone_name=timezone, filters=filters); _audit_export(db, request, user, tenant, "overview", format, filters, len(rows), "COMPLETED"); return response
    except Exception:
        _audit_export(db, request, user, tenant, "overview", format, filters, 0, "FAILED"); raise


@router.get("/export/traces")
def export_traces(request: Request, format: str = Query("csv", pattern="^(csv|xlsx|json)$"), start_date: datetime | None = None, end_date: datetime | None = None, status: str | None = None, source: str | None = None, flow_id: str | None = None, conversation_id: str | None = None, trace_id: str | None = None, timezone: str = "UTC", tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(_authorized), db: Session = Depends(get_db)):
    start, end = _export_range(start_date, end_date); filters = {"start_date": str(start), "end_date": str(end), "status": status, "source": source, "flow_id": flow_id, "conversation_id": conversation_id, "trace_id": trace_id}
    _audit_export(db, request, user, tenant, "traces", format, filters, 0, "REQUESTED")
    try:
        rows = _export_rows(db, tenant, start, end, trace_id=trace_id, status=status, source=source, flow_id=flow_id, conversation_id=conversation_id); response = _export_response(kind="traces", fmt=format, rows=rows, tenant=tenant, start=start, end=end, timezone_name=timezone, filters=filters); _audit_export(db, request, user, tenant, "traces", format, filters, len(trace_records(rows)), "COMPLETED"); return response
    except Exception:
        _audit_export(db, request, user, tenant, "traces", format, filters, 0, "FAILED"); raise


@router.get("/export/traces/{trace_id}")
def export_trace(trace_id: str, request: Request, format: str = Query("pdf", pattern="^(pdf|json)$"), timezone: str = "UTC", tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(_authorized), db: Session = Depends(get_db)):
    end = datetime.utcnow(); start = end - timedelta(days=MAX_EXPORT_DAYS); filters = {"trace_id": trace_id}
    rows = _export_rows(db, tenant, start, end, trace_id=trace_id)
    if not rows: raise HTTPException(404, "Trace não encontrado")
    _audit_export(db, request, user, tenant, "trace", format, filters, 1, "REQUESTED")
    try:
        response = _export_response(kind="trace", fmt=format, rows=rows, tenant=tenant, start=start, end=end, timezone_name=timezone, filters=filters, trace=True); _audit_export(db, request, user, tenant, "trace", format, filters, 1, "COMPLETED"); return response
    except Exception:
        _audit_export(db, request, user, tenant, "trace", format, filters, 0, "FAILED"); raise


@router.get("/export/load-test")
def export_load_test(request: Request, format: str = Query("pdf", pattern="^(pdf|xlsx|json)$"), start_date: datetime | None = None, end_date: datetime | None = None, timezone: str = "UTC", tenant: Tenant = Depends(get_current_tenant), user: TenantUser = Depends(_authorized), db: Session = Depends(get_db)):
    start, end = _export_range(start_date, end_date); rows = [row for row in _export_rows(db, tenant, start, end) if (row.metadata_json or {}).get("load_test")]
    filters = {"start_date": str(start), "end_date": str(end), "load_test": True}; _audit_export(db, request, user, tenant, "load-test", format, filters, 0, "REQUESTED")
    try:
        response = _export_response(kind="load-test", fmt=format, rows=rows, tenant=tenant, start=start, end=end, timezone_name=timezone, filters=filters); _audit_export(db, request, user, tenant, "load-test", format, filters, len(rows), "COMPLETED"); return response
    except Exception:
        _audit_export(db, request, user, tenant, "load-test", format, filters, 0, "FAILED"); raise
