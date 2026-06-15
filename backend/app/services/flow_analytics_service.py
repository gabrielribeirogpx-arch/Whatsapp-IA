from __future__ import annotations

import logging
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import case, func
from sqlalchemy.orm import Session

from app.models.flow import Flow, FlowExecution, FlowExecutionEvent, FlowNode, FlowVersion
from app.models.lead import Lead, LeadStatus
from app.models.pipeline_stage import PipelineStage
from app.models.flow_event import FlowEvent
from app.models.flow_analytics_event import FlowAnalyticsEvent
from app.models.flow_session import FlowSession

logger = logging.getLogger(__name__)

FLOW_STARTED = "FLOW_STARTED"
NODE_ENTERED = "NODE_ENTERED"
NODE_EXITED = "NODE_EXITED"
FLOW_COMPLETED = "FLOW_COMPLETED"
FLOW_ABANDONED = "FLOW_ABANDONED"
MESSAGE_SENT = "MESSAGE_SENT"
MESSAGE_RECEIVED = "MESSAGE_RECEIVED"
CONDITION_MATCHED = "CONDITION_MATCHED"
BUTTON_CLICKED = "BUTTON_CLICKED"
LIST_SELECTED = "LIST_SELECTED"

FLOW_START = "FLOW_START"
FLOW_SEND = "FLOW_SEND"
FLOW_MATCH = "FLOW_MATCH"
FLOW_FINISH = "FLOW_FINISH"
CONVERSION = "CONVERSION"
ABANDONED = "ABANDONED"

VALID_EVENT_TYPES = {
    FLOW_STARTED,
    NODE_ENTERED,
    NODE_EXITED,
    FLOW_COMPLETED,
    FLOW_ABANDONED,
    MESSAGE_SENT,
    MESSAGE_RECEIVED,
    CONDITION_MATCHED,
    BUTTON_CLICKED,
    LIST_SELECTED,
    FLOW_START,
    FLOW_SEND,
    FLOW_MATCH,
    FLOW_FINISH,
    CONVERSION,
    ABANDONED,
    "flow_started",
    "node_entered",
    "node_exited",
    "flow_completed",
    "flow_abandoned",
    "message_sent",
    "message_queued",
    "message_received",
    "condition_matched",
    "button_clicked",
    "list_selected",
    "conversion",
    "conversion_reached",
    "node_completed",
    "choice_selected",
    "transition_taken",
    "abandoned",
}

EVENT_TYPE_ALIASES: dict[str, str] = {
    FLOW_STARTED: FLOW_STARTED,
    "flow_started": FLOW_STARTED,
    FLOW_START: FLOW_STARTED,
    NODE_ENTERED: NODE_ENTERED,
    "node_entered": NODE_ENTERED,
    NODE_EXITED: NODE_EXITED,
    "node_exited": NODE_EXITED,
    FLOW_COMPLETED: FLOW_COMPLETED,
    "flow_completed": FLOW_COMPLETED,
    FLOW_FINISH: FLOW_COMPLETED,
    CONVERSION: FLOW_COMPLETED,
    "conversion": FLOW_COMPLETED,
    FLOW_ABANDONED: FLOW_ABANDONED,
    "flow_abandoned": FLOW_ABANDONED,
    ABANDONED: FLOW_ABANDONED,
    "abandoned": FLOW_ABANDONED,
    MESSAGE_SENT: MESSAGE_SENT,
    "message_sent": MESSAGE_SENT,
    "message_queued": MESSAGE_SENT,
    FLOW_SEND: MESSAGE_SENT,
    MESSAGE_RECEIVED: MESSAGE_RECEIVED,
    "message_received": MESSAGE_RECEIVED,
    CONDITION_MATCHED: CONDITION_MATCHED,
    "condition_matched": CONDITION_MATCHED,
    FLOW_MATCH: CONDITION_MATCHED,
    BUTTON_CLICKED: BUTTON_CLICKED,
    "button_clicked": BUTTON_CLICKED,
    LIST_SELECTED: LIST_SELECTED,
    "list_selected": LIST_SELECTED,
    "node_completed": NODE_EXITED,
    "choice_selected": CONDITION_MATCHED,
    "transition_taken": CONDITION_MATCHED,
    "conversion_reached": "conversion_reached",
}

PERIODS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}
DEFAULT_PERIOD = "7d"
FINAL_STATUSES = {"completed", "converted", "conversion"}
ABANDONED_STATUSES = {"abandoned", "expired"}


def resolve_analytics_period(period: str | None) -> str:
    normalized = (period or "").strip().lower()
    return normalized if normalized in PERIODS else DEFAULT_PERIOD


def _safe_rate(numerator: float, denominator: float) -> float:
    return round((numerator / denominator) * 100, 2) if denominator else 0.0


def _normalize_event_type(event_type: str | None) -> str:
    if not event_type:
        return ""
    return EVENT_TYPE_ALIASES.get(event_type, EVENT_TYPE_ALIASES.get(event_type.upper(), event_type.upper()))


def _empty_response(flow_id: str, flow_name: str | None, period: str) -> dict[str, Any]:
    timeline: list[dict[str, Any]] = []
    return {
        "flow_id": flow_id,
        "flow_name": flow_name or "Flow",
        "period": period,
        "summary": {
            "entries": 0,
            "conversions": 0,
            "conversion_rate": 0,
            "abandonments": 0,
            "abandonment_rate": 0,
            "avg_duration_seconds": 0,
            "messages_handled": 0,
            "messages": 0,
            "messages_sent": 0,
            "completed": 0,
            "dropoff_rate": 0,
            "avg_time": 0,
            "avg_time_seconds": 0,
            "avg_messages_per_user": 0,
        },
        "kpis": {
            "entries": 0,
            "conversion_rate": 0,
            "abandonment_rate": 0,
            "avg_time_seconds": 0,
            "handled_messages": 0,
        },
        "funnel": [],
        "dropoffs": [],
        "top_dropoffs": [],
        "common_responses": [],
        "common_replies": [],
        "timeseries": timeline,
        "timeline": timeline,
        "insights": [],
    }


def _coerce_uuid(value: Any) -> uuid.UUID | None:
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value)) if value else None
    except (TypeError, ValueError):
        return None




def track_flow_event(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    flow_id: uuid.UUID,
    event_type: str,
    flow_version_id: uuid.UUID | None = None,
    session_id: uuid.UUID | None = None,
    conversation_id: uuid.UUID | None = None,
    contact_id: uuid.UUID | None = None,
    node_id: str | None = None,
    node_type: str | None = None,
    event_key: str | None = None,
    value: Any | None = None,
    metadata: dict[str, Any] | None = None,
) -> FlowAnalyticsEvent | None:
    try:
        if event_type == "conversion_reached" and session_id and node_id:
            existing = (
                db.query(FlowAnalyticsEvent.id)
                .filter(
                    FlowAnalyticsEvent.tenant_id == tenant_id,
                    FlowAnalyticsEvent.flow_id == flow_id,
                    FlowAnalyticsEvent.session_id == session_id,
                    FlowAnalyticsEvent.node_id == str(node_id),
                    FlowAnalyticsEvent.event_type == "conversion_reached",
                )
                .first()
            )
            if existing:
                return None
        event = FlowAnalyticsEvent(
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_version_id=flow_version_id,
            session_id=session_id,
            conversation_id=conversation_id,
            contact_id=contact_id,
            node_id=str(node_id) if node_id else None,
            node_type=node_type,
            event_type=event_type,
            event_key=event_key,
            value=value,
            metadata_json=metadata or {},
        )
        db.add(event)
        return event
    except Exception as exc:  # pragma: no cover - defensive: analytics cannot break runtime
        logger.warning("event=flow_analytics_track_failed flow_id=%s tenant_id=%s event_type=%s error=%s", flow_id, tenant_id, event_type, exc)
        return None

def _complete_flow_crm_integration(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    flow_id: uuid.UUID,
    contact_id: uuid.UUID | None,
    conversation_id: uuid.UUID | None,
    user_phone: str | None,
    occurred_at: datetime,
) -> None:
    if not contact_id and not conversation_id and not user_phone:
        return

    lead = (
        db.query(Lead)
        .filter(
            Lead.tenant_id == tenant_id,
            Lead.status == LeadStatus.ACTIVE.value,
        )
        .filter(
            (Lead.contact_id == contact_id) if contact_id else (Lead.conversation_id == conversation_id) if conversation_id else (Lead.phone == user_phone)
        )
        .first()
    )
    if not lead and user_phone:
        lead = Lead(
            tenant_id=tenant_id,
            phone=user_phone,
            name=user_phone,
            contact_id=contact_id,
            conversation_id=conversation_id,
            source="whatsapp",
            status=LeadStatus.ACTIVE.value,
            last_interaction=occurred_at,
            last_contact_at=occurred_at,
            entered_stage_at=occurred_at,
            created_at=occurred_at,
            updated_at=occurred_at,
        )
        db.add(lead)
        db.flush()

    if not lead:
        return

    final_stage = (
        db.query(PipelineStage)
        .filter(PipelineStage.tenant_id == tenant_id, PipelineStage.is_final_stage.is_(True))
        .order_by(PipelineStage.position.desc(), PipelineStage.created_at.desc())
        .first()
    )
    if final_stage and lead.stage_id != final_stage.id:
        lead.stage_id = final_stage.id
        lead.stage = final_stage.name
        lead.entered_stage_at = occurred_at
    if contact_id and not lead.contact_id:
        lead.contact_id = contact_id
    if conversation_id and not lead.conversation_id:
        lead.conversation_id = conversation_id
    lead.last_interaction = occurred_at
    lead.last_contact_at = occurred_at
    lead.updated_at = occurred_at
    db.add(lead)

def _find_execution(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    flow_id: uuid.UUID,
    conversation_id: uuid.UUID,
    flow_version_id: uuid.UUID | None,
) -> FlowExecution | None:
    query = (
        db.query(FlowExecution)
        .filter(
            FlowExecution.tenant_id == tenant_id,
            FlowExecution.flow_id == flow_id,
            FlowExecution.conversation_id == conversation_id,
        )
        .order_by(FlowExecution.started_at.desc(), FlowExecution.updated_at.desc())
    )
    if flow_version_id:
        version_match = query.filter(FlowExecution.flow_version_id == flow_version_id).first()
        if version_match:
            return version_match
    return query.first()


def _resolve_persisted_flow_event_node_id(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    flow_id: uuid.UUID | None,
    node_id: uuid.UUID | str | None,
    metadata_payload: dict[str, Any],
) -> uuid.UUID | None:
    coerced_node_id = _coerce_uuid(node_id)
    if not coerced_node_id:
        return None
    if not flow_id:
        metadata_payload.setdefault("runtime_node_id", str(coerced_node_id))
        metadata_payload.setdefault("node_id_unpersisted", True)
        return None

    persisted_node = (
        db.query(FlowNode.id)
        .filter(
            FlowNode.id == coerced_node_id,
            FlowNode.tenant_id == tenant_id,
            FlowNode.flow_id == flow_id,
        )
        .first()
    )
    if persisted_node:
        return coerced_node_id

    candidate_versions = (
        db.query(FlowVersion.id, FlowVersion.nodes)
        .filter(FlowVersion.flow_id == flow_id, FlowVersion.tenant_id == tenant_id)
        .order_by(FlowVersion.is_published.desc(), FlowVersion.is_active.desc(), FlowVersion.created_at.desc())
        .all()
    )
    version_with_node = next(
        (version_id for version_id, version_nodes in candidate_versions if any(str(node.get("id")) == str(coerced_node_id) for node in (version_nodes or []) if isinstance(node, dict))),
        None,
    )
    if version_with_node:
        metadata_payload.setdefault("runtime_node_id", str(coerced_node_id))
        metadata_payload.setdefault("node_id_version_only", True)
        logger.info(
            "event=flow_event_node_version_only flow_id=%s tenant_id=%s runtime_node_id=%s flow_version_id=%s",
            flow_id,
            tenant_id,
            coerced_node_id,
            version_with_node,
        )
        return None

    metadata_payload.setdefault("runtime_node_id", str(coerced_node_id))
    metadata_payload.setdefault("node_id_unpersisted", True)
    logger.warning(
        "event=flow_event_node_unpersisted flow_id=%s tenant_id=%s runtime_node_id=%s",
        flow_id,
        tenant_id,
        coerced_node_id,
    )
    return None


def record_flow_event(
    db: Session,
    *,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    flow_id: uuid.UUID | None,
    flow_version_id: uuid.UUID | None,
    node_id: uuid.UUID | str | None,
    event_type: str,
    user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    if event_type not in VALID_EVENT_TYPES:
        logger.warning("event=flow_event_skip reason=invalid_type event_type=%s", event_type)
        return
    normalized_type = _normalize_event_type(event_type)
    node_text = str(node_id) if node_id else None
    metadata_payload = dict(metadata or {})
    persisted_node_id = _resolve_persisted_flow_event_node_id(
        db,
        tenant_id=tenant_id,
        flow_id=flow_id,
        node_id=node_id,
        metadata_payload=metadata_payload,
    )

    db.add(
        FlowEvent(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            flow_id=flow_id,
            flow_version_id=flow_version_id,
            node_id=persisted_node_id,
            event_type=normalized_type,
            user_id=user_id,
            metadata_json=metadata_payload,
        )
    )

    if not flow_id:
        return

    execution = _find_execution(
        db,
        tenant_id=tenant_id,
        flow_id=flow_id,
        conversation_id=conversation_id,
        flow_version_id=flow_version_id,
    )
    if not execution:
        latest_session = (
            db.query(FlowSession)
            .filter(
                FlowSession.tenant_id == tenant_id,
                FlowSession.flow_id == flow_id,
                FlowSession.conversation_id == str(conversation_id),
            )
            .order_by(FlowSession.created_at.desc(), FlowSession.updated_at.desc())
            .first()
        )
        if latest_session:
            execution = FlowExecution(
                id=latest_session.id,
                tenant_id=tenant_id,
                flow_id=flow_id,
                flow_version_id=latest_session.flow_version_id or flow_version_id,
                conversation_id=conversation_id,
                user_phone=latest_session.user_identifier,
                started_at=latest_session.created_at or datetime.utcnow(),
                status=latest_session.status or "running",
                current_node=latest_session.current_node_id,
                current_node_id=latest_session.current_node_id,
                completed=(latest_session.status or "").lower() in FINAL_STATUSES,
                state=latest_session.context if isinstance(latest_session.context, dict) else {},
            )
            db.add(execution)
            db.flush()
    if not execution and normalized_type in {FLOW_STARTED, NODE_ENTERED, MESSAGE_SENT, MESSAGE_RECEIVED}:
        execution = FlowExecution(
            tenant_id=tenant_id,
            flow_id=flow_id,
            flow_version_id=flow_version_id,
            contact_id=_coerce_uuid(metadata_payload.get("contact_id")),
            conversation_id=conversation_id,
            user_phone=user_id or metadata_payload.get("phone"),
            started_at=datetime.utcnow(),
            status="running",
            current_node=node_text,
            current_node_id=node_text,
            completed=False,
            state={},
        )
        db.add(execution)
        db.flush()

    if not execution:
        return

    now = datetime.utcnow()
    if normalized_type == FLOW_STARTED and not execution.started_at:
        execution.started_at = now
    if normalized_type == NODE_ENTERED and node_text:
        execution.current_node = node_text
        execution.current_node_id = node_text
    if normalized_type == FLOW_COMPLETED:
        execution.status = "completed"
        execution.completed = True
        execution.completed_at = now
        if flow_id:
            _complete_flow_crm_integration(
                db,
                tenant_id=tenant_id,
                flow_id=flow_id,
                contact_id=execution.contact_id or _coerce_uuid(metadata_payload.get("contact_id")),
                conversation_id=conversation_id,
                user_phone=execution.user_phone or user_id or metadata_payload.get("phone"),
                occurred_at=now,
            )
    elif normalized_type == FLOW_ABANDONED:
        execution.status = "abandoned"
        execution.completed = False
        execution.completed_at = now
    execution.updated_at = now
    db.add(FlowExecutionEvent(execution_id=execution.id, node_id=node_text, event_type=normalized_type, created_at=now))


def _node_label(node: FlowNode) -> str:
    metadata = node.metadata_json if isinstance(node.metadata_json, dict) else {}
    for key in ("label", "title", "content", "text"):
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()[:80]
    return (node.content or "Bloco")[:80]


def _node_map(db: Session, flow_id: uuid.UUID) -> dict[str, dict[str, str]]:
    rows = db.query(FlowNode).filter(FlowNode.flow_id == flow_id).all()
    return {str(row.id): {"type": row.type or "unknown", "label": _node_label(row)} for row in rows}


def _load_executions(db: Session, tenant_id: uuid.UUID, flow_id: uuid.UUID, period_start: datetime) -> list[FlowExecution]:
    executions = (
        db.query(FlowExecution)
        .filter(
            FlowExecution.tenant_id == tenant_id,
            FlowExecution.flow_id == flow_id,
            FlowExecution.started_at >= period_start,
        )
        .order_by(FlowExecution.started_at.asc())
        .all()
    )
    if executions:
        return executions

    sessions = (
        db.query(FlowSession)
        .filter(
            FlowSession.tenant_id == tenant_id,
            FlowSession.flow_id == flow_id,
            FlowSession.created_at >= period_start,
        )
        .all()
    )
    fallback: list[FlowExecution] = []
    for session in sessions:
        started_at = session.created_at or datetime.utcnow()
        completed = (session.status or "").lower() in FINAL_STATUSES
        fallback.append(
            FlowExecution(
                id=session.id,
                tenant_id=tenant_id,
                flow_id=flow_id,
                flow_version_id=session.flow_version_id,
                conversation_id=_coerce_uuid(session.conversation_id),
                user_phone=session.user_identifier,
                started_at=started_at,
                completed_at=session.updated_at if completed else None,
                status=session.status,
                current_node=session.current_node_id,
                current_node_id=session.current_node_id,
                completed=completed,
                state={},
                updated_at=session.updated_at,
            )
        )
    return fallback


def _load_events(db: Session, tenant_id: uuid.UUID, flow_id: uuid.UUID, period_start: datetime) -> list[tuple[Any, str, str | None, datetime | None]]:
    execution_ids = [row.id for row in db.query(FlowExecution.id).filter(FlowExecution.tenant_id == tenant_id, FlowExecution.flow_id == flow_id, FlowExecution.started_at >= period_start).all()]
    events: list[tuple[Any, str, str | None, datetime | None]] = []
    if execution_ids:
        for event in db.query(FlowExecutionEvent).filter(FlowExecutionEvent.execution_id.in_(execution_ids)).order_by(FlowExecutionEvent.created_at.asc()).all():
            events.append((event, _normalize_event_type(event.event_type), event.node_id, event.created_at))
    if events:
        return events

    legacy_events = (
        db.query(FlowEvent)
        .filter(FlowEvent.tenant_id == tenant_id, FlowEvent.flow_id == flow_id, FlowEvent.created_at >= period_start)
        .order_by(FlowEvent.created_at.asc())
        .all()
    )
    return [(event, _normalize_event_type(event.event_type), str(event.node_id) if event.node_id else None, event.created_at) for event in legacy_events]


def get_flow_list_metrics(db: Session, *, tenant_id: uuid.UUID) -> dict[uuid.UUID, dict[str, Any]]:
    rows = (
        db.query(
            FlowExecution.flow_id,
            func.count(FlowExecution.id),
            func.sum(case((FlowExecution.completed.is_(True), 1), else_=0)),
            func.max(FlowExecution.started_at),
        )
        .filter(FlowExecution.tenant_id == tenant_id, FlowExecution.flow_id.isnot(None))
        .group_by(FlowExecution.flow_id)
        .all()
    )
    metrics: dict[uuid.UUID, dict[str, Any]] = {}
    for flow_id, total_entries, total_completions, last_execution_at in rows:
        entries = int(total_entries or 0)
        completions = int(total_completions or 0)
        metrics[flow_id] = {
            "total_entries": entries,
            "total_completions": completions,
            "conversion_rate": _safe_rate(completions, entries),
            "last_execution_at": last_execution_at.isoformat() if last_execution_at else None,
        }

    legacy_rows = (
        db.query(FlowSession.flow_id, func.count(FlowSession.id), func.max(FlowSession.created_at))
        .filter(FlowSession.tenant_id == tenant_id)
        .group_by(FlowSession.flow_id)
        .all()
    )
    for flow_id, total_entries, last_execution_at in legacy_rows:
        metrics.setdefault(
            flow_id,
            {
                "total_entries": int(total_entries or 0),
                "total_completions": 0,
                "conversion_rate": 0,
                "last_execution_at": last_execution_at.isoformat() if last_execution_at else None,
            },
        )
    return metrics


def _flow_version_node_map(db: Session, tenant_id: uuid.UUID, flow_id: uuid.UUID) -> dict[str, dict[str, str]]:
    mapped = _node_map(db, flow_id)
    versions = (
        db.query(FlowVersion.nodes)
        .filter(FlowVersion.tenant_id == tenant_id, FlowVersion.flow_id == flow_id)
        .order_by(FlowVersion.is_published.desc(), FlowVersion.is_active.desc(), FlowVersion.created_at.desc())
        .all()
    )
    for (nodes,) in versions:
        for node in nodes or []:
            if not isinstance(node, dict) or node.get("id") is None:
                continue
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            label = next((str(data.get(k)).strip() for k in ("label", "title", "content", "text", "message") if data.get(k)), "Bloco")
            mapped.setdefault(str(node["id"]), {"label": label[:80], "type": str(node.get("type") or data.get("type") or "unknown")})
    return mapped


def _analytics_events(db: Session, tenant_id: uuid.UUID, flow_id: uuid.UUID, period_start: datetime) -> list[FlowAnalyticsEvent]:
    return (
        db.query(FlowAnalyticsEvent)
        .filter(
            FlowAnalyticsEvent.tenant_id == tenant_id,
            FlowAnalyticsEvent.flow_id == flow_id,
            FlowAnalyticsEvent.created_at >= period_start,
        )
        .order_by(FlowAnalyticsEvent.created_at.asc())
        .all()
    )


def get_flow_analytics(db: Session, *, tenant_id: uuid.UUID, flow_id: uuid.UUID, period: str = DEFAULT_PERIOD, range_days: int | None = None) -> dict[str, Any]:
    resolved_period = resolve_analytics_period(period)
    flow = db.query(Flow).filter(Flow.id == flow_id, Flow.tenant_id == tenant_id).first()
    base = _empty_response(str(flow_id), flow.name if flow else None, resolved_period)
    if not flow:
        return base

    period_start = datetime.utcnow() - (timedelta(days=range_days) if range_days else PERIODS[resolved_period])
    analytics_events = _analytics_events(db, tenant_id, flow_id, period_start)
    if not analytics_events:
        # Backward compatible fallback for historical pre-Runtime-V2 analytics.
        return _get_legacy_flow_analytics(db=db, tenant_id=tenant_id, flow_id=flow_id, period=resolved_period)

    node_map = _flow_version_node_map(db, tenant_id, flow_id)
    session_ids = {event.session_id for event in analytics_events if event.session_id}
    entries = sum(1 for event in analytics_events if event.event_type == "flow_started")
    conversions = sum(1 for event in analytics_events if event.event_type == "conversion_reached")
    completed = sum(1 for event in analytics_events if event.event_type == "flow_completed")
    handled_messages = sum(1 for event in analytics_events if event.event_type in {"message_sent", "message_received"})

    session_event_types: defaultdict[uuid.UUID, set[str]] = defaultdict(set)
    session_last_at: dict[uuid.UUID, datetime] = {}
    session_started_at: dict[uuid.UUID, datetime] = {}
    for event in analytics_events:
        if not event.session_id:
            continue
        session_event_types[event.session_id].add(event.event_type)
        session_last_at[event.session_id] = max(session_last_at.get(event.session_id, event.created_at), event.created_at)
        if event.event_type == "flow_started":
            session_started_at.setdefault(event.session_id, event.created_at)

    abandon_cutoff = datetime.utcnow() - timedelta(minutes=30)
    abandoned_sessions = {
        sid for sid in session_ids
        if "flow_completed" not in session_event_types[sid]
        and "conversion_reached" not in session_event_types[sid]
        and session_last_at.get(sid, datetime.utcnow()) < abandon_cutoff
    }
    abandoned = len(abandoned_sessions)

    durations = []
    for sid, started_at in session_started_at.items():
        end_events = [e.created_at for e in analytics_events if e.session_id == sid and e.event_type in {"flow_completed", "conversion_reached"}]
        if end_events:
            durations.append((min(end_events) - started_at).total_seconds())
    avg_duration_seconds = round(sum(durations) / len(durations), 2) if durations else 0

    node_entered: Counter[str] = Counter()
    node_completed: Counter[str] = Counter()
    for event in analytics_events:
        if not event.node_id:
            continue
        if event.event_type == "node_entered":
            node_entered[event.node_id] += 1
        elif event.event_type == "node_completed":
            node_completed[event.node_id] += 1
    funnel = []
    for node_id, entered in node_entered.most_common():
        meta = node_map.get(node_id, {"label": "Bloco", "type": "unknown"})
        completed_count = min(node_completed[node_id], entered)
        dropoff = max(entered - completed_count, 0)
        funnel.append({"node_id": node_id, "node_label": meta["label"], "node_type": meta["type"], "entered": entered, "completed": completed_count, "dropoff": dropoff, "dropoff_rate": _safe_rate(dropoff, entered), "entries": entered, "dropoffs": dropoff, "conversion_to_next_rate": _safe_rate(completed_count, entered)})
    dropoff_points = sorted((item for item in funnel if item["dropoff"] > 0), key=lambda item: item["dropoff"], reverse=True)[:5]

    replies: Counter[str] = Counter()
    for event in analytics_events:
        if event.event_type not in {"message_received", "choice_selected"}:
            continue
        metadata = event.metadata_json if isinstance(event.metadata_json, dict) else {}
        text = metadata.get("text") or metadata.get("reply") or event.event_key
        if isinstance(text, str) and text.strip():
            replies[text.strip()] += 1
    common_replies = [{"text": text, "reply": text, "count": count, "rate": _safe_rate(count, sum(replies.values()))} for text, count in replies.most_common(8)]

    daily: defaultdict[str, dict[str, Any]] = defaultdict(lambda: {"entries": 0, "conversions": 0, "abandonments": 0, "messages": 0})
    for event in analytics_events:
        bucket = event.created_at.date().isoformat()
        if event.event_type == "flow_started": daily[bucket]["entries"] += 1
        elif event.event_type == "conversion_reached": daily[bucket]["conversions"] += 1
        elif event.event_type == "flow_abandoned": daily[bucket]["abandonments"] += 1
        elif event.event_type in {"message_sent", "message_received"}: daily[bucket]["messages"] += 1
    timeseries = [{"date": date, **metrics} for date, metrics in sorted(daily.items())]

    summary = {"entries": entries, "conversions": conversions, "conversion_rate": _safe_rate(conversions, entries), "abandonments": abandoned, "abandonment_rate": _safe_rate(abandoned, entries), "avg_duration_seconds": avg_duration_seconds, "messages_handled": handled_messages, "completed": completed, "messages": handled_messages, "messages_sent": handled_messages, "dropoff_rate": _safe_rate(abandoned, entries), "avg_time_seconds": avg_duration_seconds}
    base.update({"summary": summary, "kpis": {"entries": entries, "conversion_rate": summary["conversion_rate"], "abandonment_rate": summary["abandonment_rate"], "avg_time_seconds": avg_duration_seconds, "handled_messages": handled_messages}, "funnel": funnel, "dropoff_points": dropoff_points, "dropoffs": dropoff_points, "top_dropoffs": dropoff_points, "common_replies": common_replies, "common_responses": common_replies, "timeseries": timeseries, "timeline": timeseries})
    return base


def _get_legacy_flow_analytics(db: Session, *, tenant_id: uuid.UUID, flow_id: uuid.UUID, period: str = DEFAULT_PERIOD) -> dict[str, Any]:
    resolved_period = resolve_analytics_period(period)
    flow = db.query(Flow).filter(Flow.id == flow_id, Flow.tenant_id == tenant_id).first()
    base = _empty_response(str(flow_id), flow.name if flow else None, resolved_period)
    if not flow:
        return base

    period_start = datetime.utcnow() - PERIODS[resolved_period]
    executions = _load_executions(db, tenant_id, flow_id, period_start)
    events = _load_events(db, tenant_id, flow_id, period_start)
    node_map = _node_map(db, flow_id)

    entries = len(executions)
    completed = sum(1 for execution in executions if bool(execution.completed) or (execution.status or "").lower() in FINAL_STATUSES)
    abandoned = sum(1 for execution in executions if (execution.status or "").lower() in ABANDONED_STATUSES)
    handled_messages = sum(1 for _, normalized_type, _, _ in events if normalized_type in {MESSAGE_SENT, MESSAGE_RECEIVED})

    durations = []
    for execution in executions:
        if execution.started_at and execution.completed_at:
            seconds = (execution.completed_at - execution.started_at).total_seconds()
            if seconds >= 0:
                durations.append(seconds)
    avg_time_seconds = round(sum(durations) / len(durations), 2) if durations else 0

    node_entries: Counter[str] = Counter()
    node_exits: Counter[str] = Counter()
    for _, normalized_type, node_id, _ in events:
        if not node_id:
            continue
        if normalized_type == NODE_ENTERED:
            node_entries[str(node_id)] += 1
        elif normalized_type in {NODE_EXITED, FLOW_COMPLETED, FLOW_ABANDONED}:
            node_exits[str(node_id)] += 1

    funnel = []
    total_node_entries = sum(node_entries.values())
    for node_id, count in node_entries.most_common():
        meta = node_map.get(node_id, {"label": "Bloco", "type": "unknown"})
        exits = min(node_exits[node_id], count)
        dropoff_rate = _safe_rate(max(count - exits, 0), count)
        funnel.append({
            "node_id": node_id,
            "node_label": meta["label"],
            "node_type": meta["type"],
            "entries": count,
            "exits": exits,
            "dropoffs": max(count - exits, 0),
            "dropoff_rate": dropoff_rate,
            "conversion_to_next_rate": _safe_rate(exits, count),
            "avg_time_seconds": 0,
            "conversion_rate": _safe_rate(count, total_node_entries),
        })

    daily: defaultdict[str, dict[str, Any]] = defaultdict(lambda: {"entries": 0, "messages_sent": 0, "messages": 0, "completed": 0, "conversions": 0, "abandonments": 0})
    for execution in executions:
        if execution.started_at:
            daily[execution.started_at.date().isoformat()]["entries"] += 1
        if execution.completed_at and (execution.completed or (execution.status or "").lower() in FINAL_STATUSES):
            bucket = execution.completed_at.date().isoformat()
            daily[bucket]["completed"] += 1
            daily[bucket]["conversions"] += 1
        if execution.completed_at and (execution.status or "").lower() in ABANDONED_STATUSES:
            daily[execution.completed_at.date().isoformat()]["abandonments"] += 1
    for _, normalized_type, _, created_at in events:
        if created_at and normalized_type in {MESSAGE_SENT, MESSAGE_RECEIVED}:
            bucket = created_at.date().isoformat()
            daily[bucket]["messages_sent"] += 1
            daily[bucket]["messages"] += 1
    timeline = [{"date": date, **metrics} for date, metrics in sorted(daily.items())]

    responses: Counter[str] = Counter()
    legacy_response_total = 0
    for event, normalized_type, _, _ in events:
        if normalized_type != MESSAGE_RECEIVED:
            continue
        metadata = getattr(event, "metadata_json", None)
        if isinstance(metadata, dict):
            text = metadata.get("text") or metadata.get("reply")
            if isinstance(text, str) and text.strip():
                responses[text.strip()] += 1
                legacy_response_total += 1
    common_replies = [{"reply": text, "count": count, "rate": _safe_rate(count, legacy_response_total)} for text, count in responses.most_common(8)]

    summary = {
        "entries": entries,
        "messages": handled_messages,
        "messages_sent": handled_messages,
        "completed": completed,
        "conversion_rate": _safe_rate(completed, entries),
        "dropoff_rate": _safe_rate(abandoned, entries),
        "avg_time": avg_time_seconds,
        "avg_time_seconds": avg_time_seconds,
        "avg_messages_per_user": round(handled_messages / entries, 2) if entries else 0,
    }
    dropoffs = sorted([item for item in funnel if item["dropoff_rate"] > 0], key=lambda item: item["dropoff_rate"], reverse=True)
    base.update({
        "summary": summary,
        "kpis": {
            "entries": entries,
            "conversion_rate": summary["conversion_rate"],
            "abandonment_rate": summary["dropoff_rate"],
            "avg_time_seconds": avg_time_seconds,
            "handled_messages": handled_messages,
        },
        "funnel": funnel,
        "dropoffs": dropoffs,
        "top_dropoffs": dropoffs[:5],
        "common_responses": common_replies,
        "common_replies": common_replies,
        "timeseries": timeline,
        "timeline": timeline,
        "insights": [],
    })
    return base
