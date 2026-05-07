from __future__ import annotations

import logging
import uuid
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from statistics import mean
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


def _build_dataset(db: Session, tenant_id: uuid.UUID, flow_id: uuid.UUID, since: datetime) -> tuple[list[FlowSession], list[FlowEvent]]:
    sessions = (
        db.query(FlowSession)
        .filter(
            FlowSession.tenant_id == tenant_id,
            FlowSession.flow_id == flow_id,
            FlowSession.started_at >= since,
        )
        .all()
    )

    events = (
        db.query(FlowEvent)
        .filter(
            FlowEvent.tenant_id == tenant_id,
            FlowEvent.flow_id == flow_id,
            FlowEvent.created_at >= since,
        )
        .order_by(FlowEvent.created_at.asc())
        .all()
    )

    for event in events:
        event.event_type = _normalize_event_type(event.event_type)

    return sessions, events


def _compute_kpis(sessions: list[FlowSession], events: list[FlowEvent]) -> dict[str, Any]:
    entries = len(sessions)
    conversions = sum(1 for session in sessions if (session.completion_status or "").lower() == "converted")
    abandonments = sum(1 for session in sessions if (session.completion_status or "").lower() == "abandoned")

    elapsed_times = [
        max((session.ended_at - session.started_at).total_seconds(), 0)
        for session in sessions
        if session.started_at and session.ended_at
    ]

    handled_messages = sum(1 for event in events if event.event_type in {MESSAGE_SENT, MESSAGE_RECEIVED})

    return {
        "entries": entries,
        "conversion_rate": _safe_rate(conversions, entries),
        "abandonment_rate": _safe_rate(abandonments, entries),
        "avg_time_seconds": round(mean(elapsed_times), 2) if elapsed_times else 0,
        "handled_messages": handled_messages,
    }


def _compute_timeseries(sessions: list[FlowSession], events: list[FlowEvent]) -> list[dict[str, Any]]:
    daily: defaultdict[str, dict[str, Any]] = defaultdict(lambda: {"entries": 0, "conversions": 0, "abandonments": 0, "messages": 0})

    for session in sessions:
        if session.started_at:
            daily[session.started_at.date().isoformat()]["entries"] += 1
        if session.conversion_at:
            daily[session.conversion_at.date().isoformat()]["conversions"] += 1
        if session.ended_at and (session.completion_status or "").lower() == "abandoned":
            daily[session.ended_at.date().isoformat()]["abandonments"] += 1

    for event in events:
        if event.event_type in {MESSAGE_SENT, MESSAGE_RECEIVED} and event.created_at:
            daily[event.created_at.date().isoformat()]["messages"] += 1

    return [{"date": dt, **metrics} for dt, metrics in sorted(daily.items())]


def _compute_funnel(sessions: list[FlowSession], events: list[FlowEvent], node_map: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    node_entries: Counter[str] = Counter()
    node_sessions: defaultdict[str, set[str]] = defaultdict(set)
    converted_sessions = {
        str(session.conversation_id)
        for session in sessions
        if (session.completion_status or "").lower() in {"converted", "conversion", "completed"}
    }

    last_node_by_session: dict[str, str] = {}
    for event in events:
        session_key = str(event.conversation_id)
        if event.event_type == NODE_ENTERED and event.node_id:
            node_id = str(event.node_id)
            node_entries[node_id] += 1
            node_sessions[node_id].add(session_key)
            last_node_by_session[session_key] = node_id

    abandoned_last_node: Counter[str] = Counter()
    abandoned_session_keys = {
        str(session.conversation_id)
        for session in sessions
        if (session.completion_status or "").lower() == "abandoned" and session.conversation_id
    }
    for session_key in abandoned_session_keys:
        node_id = last_node_by_session.get(session_key)
        if node_id:
            abandoned_last_node[node_id] += 1

    funnel: list[dict[str, Any]] = []
    for node_id, entries in node_entries.most_common():
        sessions_in_node = node_sessions.get(node_id, set())
        conversions = len(sessions_in_node.intersection(converted_sessions))
        node_meta = node_map.get(node_id, {"label": "Node", "type": "unknown"})
        funnel.append(
            {
                "node_id": node_id,
                "node_label": node_meta["label"],
                "node_type": node_meta["type"],
                "entries": entries,
                "dropoffs": abandoned_last_node.get(node_id, 0),
                "conversion_rate": _safe_rate(conversions, len(sessions_in_node)),
            }
        )

    return funnel


def _compute_dropoffs(sessions: list[FlowSession], events: list[FlowEvent], node_map: dict[str, dict[str, str]]) -> list[dict[str, Any]]:
    last_node_by_session: dict[str, str] = {}
    for event in events:
        if event.event_type == NODE_ENTERED and event.node_id:
            last_node_by_session[str(event.conversation_id)] = str(event.node_id)

    dropoff_counter: Counter[str] = Counter()
    for session in sessions:
        if (session.completion_status or "").lower() != "abandoned" or not session.conversation_id:
            continue
        last_node = last_node_by_session.get(str(session.conversation_id))
        if last_node:
            dropoff_counter[last_node] += 1

    return [
        {
            "node_id": node_id,
            "node_label": node_map.get(node_id, {}).get("label", "Node"),
            "node_type": node_map.get(node_id, {}).get("type", "unknown"),
            "count": count,
        }
        for node_id, count in dropoff_counter.most_common()
    ]


def _compute_common_responses(events: list[FlowEvent]) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    for event in events:
        if event.event_type != MESSAGE_RECEIVED:
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

    since = datetime.now(UTC).replace(tzinfo=None) - PERIODS[resolved_period]
    sessions, events = _build_dataset(db, tenant_id, flow_id, since)

    node_rows = db.query(FlowNode.id, FlowNode.type, FlowNode.label).filter(FlowNode.flow_id == flow_id).all()
    node_map = {str(node_id): {"type": node_type or "unknown", "label": label or "Node"} for node_id, node_type, label in node_rows}

    kpis = _compute_kpis(sessions, events)
    timeseries = _compute_timeseries(sessions, events)
    funnel = _compute_funnel(sessions, events, node_map)
    dropoffs = _compute_dropoffs(sessions, events, node_map)
    common_responses = _compute_common_responses(events)

    entries = kpis["entries"]
    completed = sum(1 for session in sessions if (session.completion_status or "").lower() in {"converted", "conversion", "completed"})

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
