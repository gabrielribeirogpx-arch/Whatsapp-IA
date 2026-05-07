from __future__ import annotations

import logging
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.orm import Session

from app.models.flow import Flow, FlowNode
from app.models.flow_event import FlowEvent
from app.models.flow_session import FlowSession

logger = logging.getLogger(__name__)

FLOW_STARTED = "flow_started"
NODE_ENTERED = "node_entered"
MESSAGE_SENT = "message_sent"
CONDITION_MATCHED = "condition_matched"
FLOW_COMPLETED = "flow_completed"
FLOW_ABANDONED = "flow_abandoned"
MESSAGE_RECEIVED = "message_received"
CONVERSION = "conversion"
ABANDONED = "abandoned"

FLOW_START = "FLOW_START"
FLOW_SEND = "FLOW_SEND"
FLOW_MATCH = "FLOW_MATCH"
FLOW_FINISH = "FLOW_FINISH"

VALID_EVENT_TYPES = {
    FLOW_STARTED,
    NODE_ENTERED,
    MESSAGE_SENT,
    CONDITION_MATCHED,
    FLOW_COMPLETED,
    FLOW_ABANDONED,
    MESSAGE_RECEIVED,
    CONVERSION,
    ABANDONED,
}

EVENT_TYPE_ALIASES: dict[str, str] = {
    FLOW_START: FLOW_STARTED,
    FLOW_STARTED: FLOW_STARTED,
    FLOW_SEND: MESSAGE_SENT,
    MESSAGE_SENT: MESSAGE_SENT,
    FLOW_MATCH: CONDITION_MATCHED,
    CONDITION_MATCHED: CONDITION_MATCHED,
    FLOW_FINISH: FLOW_COMPLETED,
    FLOW_COMPLETED: FLOW_COMPLETED,
    FLOW_ABANDONED: ABANDONED,
    ABANDONED: ABANDONED,
    MESSAGE_RECEIVED: MESSAGE_RECEIVED,
    CONVERSION: CONVERSION,
}

PERIODS: dict[str, timedelta] = {
    "24h": timedelta(hours=24),
    "7d": timedelta(days=7),
    "30d": timedelta(days=30),
    "90d": timedelta(days=90),
}

DEFAULT_PERIOD = "7d"


@dataclass
class _SessionAnalyticsRow:
    conversation_id: uuid.UUID | None
    created_at: datetime | None


def resolve_analytics_period(period: str | None) -> str:
    normalized = (period or "").strip().lower()
    return normalized if normalized in PERIODS else DEFAULT_PERIOD


def _safe_rate(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)


def _empty_response(flow_id: str, flow_name: str | None, period: str) -> dict[str, Any]:
    return {
        "flow_id": flow_id,
        "flow_name": flow_name or "Flow",
        "period": period,
        "summary": {
            "entries": 0,
            "messages": 0,
            "messages_sent": 0,
            "completed": 0,
            "conversion_rate": 0,
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
        "timeseries": [],
        "timeline": None,
        "insights": None,
    }


def _normalize_event_type(event_type: str | None) -> str:
    if not event_type:
        return ""
    return EVENT_TYPE_ALIASES.get(event_type, event_type)


def _build_dataset(db: Session, tenant_id: uuid.UUID, flow_id: uuid.UUID, period_start: datetime) -> tuple[list[_SessionAnalyticsRow], list[FlowEvent]]:
    session_rows = (
        db.query(
            FlowSession.conversation_id,
            FlowSession.created_at,
        )
        .filter(
            FlowSession.tenant_id == tenant_id,
            FlowSession.flow_id == flow_id,
            FlowSession.created_at >= period_start,
        )
        .all()
    )
    sessions = [
        _SessionAnalyticsRow(
            conversation_id=row.conversation_id,
            created_at=row.created_at,
        )
        for row in session_rows
    ]
    sessions = sessions or []

    events = (
        db.query(FlowEvent)
        .filter(
            FlowEvent.tenant_id == tenant_id,
            FlowEvent.flow_id == flow_id,
            FlowEvent.created_at >= period_start,
        )
        .order_by(FlowEvent.created_at.asc())
        .all()
    )
    events = events or []

    return sessions, events


def _compute_kpis(sessions: list[_SessionAnalyticsRow], normalized_events: list[tuple[FlowEvent, str]]) -> dict[str, Any]:
    entries = len(sessions)
    handled_messages = sum(1 for _, normalized_type in normalized_events if normalized_type in {MESSAGE_SENT, MESSAGE_RECEIVED})

    return {
        "entries": entries,
        "conversion_rate": 0,
        "abandonment_rate": 0,
        "avg_time_seconds": 0,
        "handled_messages": handled_messages,
    }


def _compute_timeseries(sessions: list[_SessionAnalyticsRow], normalized_events: list[tuple[FlowEvent, str]]) -> list[dict[str, Any]]:
    daily: defaultdict[str, dict[str, Any]] = defaultdict(lambda: {"entries": 0, "conversions": 0, "abandonments": 0, "messages": 0})

    for session in sessions:
        if session.created_at:
            daily[session.created_at.date().isoformat()]["entries"] += 1

    for event, normalized_type in normalized_events:
        if normalized_type in {MESSAGE_SENT, MESSAGE_RECEIVED} and event.created_at:
            daily[event.created_at.date().isoformat()]["messages"] += 1

    return [{"date": dt, **metrics} for dt, metrics in sorted(daily.items())]


def _compute_funnel(sessions: list[_SessionAnalyticsRow], normalized_events: list[tuple[FlowEvent, str]], node_map: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    node_entries: Counter[str] = Counter()
    for event, normalized_type in normalized_events:
        if normalized_type == NODE_ENTERED and event.node_id:
            node_id = str(event.node_id)
            node_entries[node_id] += 1

    funnel: list[dict[str, Any]] = []
    for node_id, entries in node_entries.most_common():
        node_meta = node_map.get(node_id, {"label": "Node", "type": "unknown"})
        funnel.append(
            {
                "node_id": node_id,
                "node_label": node_meta["label"],
                "node_type": node_meta["type"],
                "entries": entries,
                "dropoffs": 0,
                "conversion_rate": 0,
            }
        )

    return funnel


def _compute_dropoffs(sessions: list[_SessionAnalyticsRow], events: list[FlowEvent], node_map: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    _ = (sessions, events, node_map)
    return []


def _compute_common_responses(normalized_events: list[tuple[FlowEvent, str]]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for event, normalized_type in normalized_events:
        if normalized_type != MESSAGE_RECEIVED:
            continue
        metadata = event.metadata_json if isinstance(event.metadata_json, dict) else {}
        text = metadata.get("text")
        if isinstance(text, str) and text.strip():
            counter[text.strip()] += 1

    return [{"text": text, "count": count} for text, count in counter.most_common(8)]


def get_flow_analytics(db: Session, *, tenant_id: uuid.UUID, flow_id: uuid.UUID, period: str = DEFAULT_PERIOD) -> dict[str, Any]:
    resolved_period = resolve_analytics_period(period)
    flow = db.query(Flow).filter(Flow.id == flow_id, Flow.tenant_id == tenant_id).first()
    base = _empty_response(str(flow_id), flow.name if flow else None, resolved_period)
    if not flow:
        return base

    try:
        period_start = datetime.utcnow() - PERIODS[resolved_period]
        sessions, events = _build_dataset(db, tenant_id, flow_id, period_start)
        sessions = sessions or []
        events = events or []

        normalized_events = [
            (event, _normalize_event_type(event.event_type))
            for event in events
        ]

        node_rows = db.query(FlowNode.id, FlowNode.type, FlowNode.content).filter(FlowNode.flow_id == flow_id).all()
        node_map = {str(node_id): {"type": node_type or "unknown", "label": node_name or "Node"} for node_id, node_type, node_name in node_rows}

        kpis = _compute_kpis(sessions, normalized_events)
        timeseries = _compute_timeseries(sessions, normalized_events)
        funnel = _compute_funnel(sessions, normalized_events, node_map)
        dropoffs = _compute_dropoffs(sessions, events, node_map)
        common_responses = _compute_common_responses(normalized_events)
    except Exception as e:
        import traceback

        print("FLOW ANALYTICS ERROR:", str(e))
        traceback.print_exc()
        raise

    entries = kpis["entries"]
    completed = 0

    summary = {
        "entries": entries,
        "messages": kpis["handled_messages"],
        "messages_sent": kpis["handled_messages"],
        "completed": completed,
        "conversion_rate": kpis["conversion_rate"],
        "dropoff_rate": kpis["abandonment_rate"],
        "avg_time": kpis["avg_time_seconds"],
        "avg_time_seconds": kpis["avg_time_seconds"],
        "avg_messages_per_user": round(kpis["handled_messages"] / entries, 2) if entries else 0,
    }

    base.update(
        {
            "kpis": kpis,
            "funnel": funnel,
            "dropoffs": dropoffs,
            "top_dropoffs": dropoffs[:5],
            "common_responses": common_responses,
            "common_replies": [{"reply": item["text"], "count": item["count"], "rate": _safe_rate(item["count"], sum(x["count"] for x in common_responses) or 1)} for item in common_responses],
            "timeseries": timeseries,
            "summary": summary,
            "timeline": timeseries,
        }
    )
    return base


def record_flow_event(db: Session, *, tenant_id: uuid.UUID, conversation_id: uuid.UUID, flow_id: uuid.UUID | None, flow_version_id: uuid.UUID | None, node_id: uuid.UUID | None, event_type: str, user_id: str | None = None, metadata: dict[str, Any] | None = None) -> None:
    if event_type not in VALID_EVENT_TYPES:
        logger.warning("event=flow_event_skip reason=invalid_type event_type=%s", event_type)
        return
    db.add(FlowEvent(tenant_id=tenant_id, conversation_id=conversation_id, flow_id=flow_id, flow_version_id=flow_version_id, node_id=node_id, event_type=event_type, user_id=user_id, metadata_json=metadata or {}))
