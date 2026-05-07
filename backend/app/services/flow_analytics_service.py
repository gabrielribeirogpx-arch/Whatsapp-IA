from __future__ import annotations

import logging
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from statistics import mean
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.flow import Flow, FlowNode
from app.models.flow_event import FlowEvent

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

FLOW_START = FLOW_STARTED
FLOW_SEND = MESSAGE_SENT
FLOW_MATCH = CONDITION_MATCHED
FALLBACK = FLOW_ABANDONED
FLOW_FINISH = FLOW_COMPLETED

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
    FLOW_ABANDONED: ABANDONED,
    ABANDONED: ABANDONED,
    FLOW_COMPLETED: CONVERSION,
    CONVERSION: CONVERSION,
    MESSAGE_SENT: MESSAGE_SENT,
    MESSAGE_RECEIVED: MESSAGE_RECEIVED,
    FLOW_STARTED: FLOW_STARTED,
    NODE_ENTERED: NODE_ENTERED,
    CONDITION_MATCHED: CONDITION_MATCHED,
}


def _normalize_event_type(event_type: str) -> str:
    return EVENT_TYPE_ALIASES.get(event_type, event_type)

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

@dataclass
class SessionStats:
    started_at: datetime | None = None
    finished_at: datetime | None = None
    entries: int = 0
    completed: bool = False
    abandoned: bool = False
    messages_sent: int = 0


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
        "funnel": [],
        "top_dropoffs": [],
        "common_replies": [],
        "timeline": None,
        "insights": None,
    }


def get_flow_analytics(db: Session, *, tenant_id: uuid.UUID, flow_id: uuid.UUID, period: str = DEFAULT_PERIOD) -> dict[str, Any]:
    resolved_period = resolve_analytics_period(period)
    flow = db.query(Flow).filter(Flow.id == flow_id, Flow.tenant_id == tenant_id).first()
    base = _empty_response(str(flow_id), flow.name if flow else None, resolved_period)
    if not flow:
        return base

    since = datetime.now(UTC).replace(tzinfo=None) - PERIODS[resolved_period]
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

    timeline_stmt = (
        select(
            func.date(FlowEvent.created_at).label("dt"),
            func.count().filter(FlowEvent.event_type == FLOW_STARTED).label("entries"),
            func.count().filter(FlowEvent.event_type.in_([MESSAGE_SENT, MESSAGE_RECEIVED])).label("messages_sent"),
            func.count().filter(FlowEvent.event_type.in_([FLOW_COMPLETED, CONVERSION])).label("completed"),
        )
        .where(
            FlowEvent.tenant_id == tenant_id,
            FlowEvent.flow_id == flow_id,
            FlowEvent.created_at >= since,
        )
        .group_by(func.date(FlowEvent.created_at))
        .order_by(func.date(FlowEvent.created_at))
    )
    timeline_rows = db.execute(timeline_stmt).all()

    node_rows = db.query(FlowNode.id, FlowNode.type, FlowNode.label).filter(FlowNode.flow_id == flow_id).all()
    node_map = {str(node_id): {"type": node_type or "unknown", "label": label or "Node"} for node_id, node_type, label in node_rows}

    sessions: dict[str, SessionStats] = defaultdict(SessionStats)
    node_entries: Counter[str] = Counter()
    node_exits: Counter[str] = Counter()
    node_durations: defaultdict[str, list[float]] = defaultdict(list)
    reply_counter: Counter[str] = Counter()

    last_node_by_session: dict[str, tuple[str, datetime]] = {}

    for event in events:
        session_key = str(event.conversation_id)
        stats = sessions[session_key]
        normalized_type = _normalize_event_type(event.event_type)

        if normalized_type == FLOW_STARTED:
            stats.entries += 1
            stats.started_at = stats.started_at or event.created_at
        if normalized_type in {MESSAGE_SENT, MESSAGE_RECEIVED}:
            stats.messages_sent += 1
        if normalized_type == CONVERSION:
            stats.completed = True
            stats.finished_at = event.created_at
        if normalized_type == ABANDONED:
            stats.abandoned = True
            stats.finished_at = event.created_at

        node_id = str(event.node_id) if event.node_id else None
        if normalized_type == NODE_ENTERED and node_id:
            node_entries[node_id] += 1
            prev = last_node_by_session.get(session_key)
            if prev:
                prev_node, prev_time = prev
                node_exits[prev_node] += 1
                node_durations[prev_node].append(max((event.created_at - prev_time).total_seconds(), 0))
            last_node_by_session[session_key] = (node_id, event.created_at)

        metadata = event.metadata_json if isinstance(event.metadata_json, dict) else {}
        reply = metadata.get("reply") if isinstance(metadata.get("reply"), str) else None
        if reply:
            reply_counter[reply.strip().lower()] += 1

    entries = sum(stats.entries for stats in sessions.values())
    completed = sum(1 for stats in sessions.values() if stats.completed)
    abandoned = sum(1 for stats in sessions.values() if stats.abandoned)
    messages_sent = sum(stats.messages_sent for stats in sessions.values())
    avg_messages_per_user = round(messages_sent / len(sessions), 2) if sessions else 0

    elapsed_times: list[float] = []
    for stats in sessions.values():
        if stats.started_at and stats.finished_at:
            elapsed_times.append(max((stats.finished_at - stats.started_at).total_seconds(), 0))
    avg_time_seconds = round(mean(elapsed_times), 2) if elapsed_times else 0

    funnel = []
    for node_id, total_entries in node_entries.most_common():
        exits = node_exits.get(node_id, 0)
        dropoff_rate = _safe_rate(total_entries - exits, total_entries)
        conversion_to_next = _safe_rate(exits, total_entries)
        avg_node_time = round(mean(node_durations[node_id]), 2) if node_durations[node_id] else 0
        node_meta = node_map.get(node_id, {"label": "Node", "type": "unknown"})
        funnel.append({
            "node_id": node_id,
            "node_label": node_meta["label"],
            "node_type": node_meta["type"],
            "entries": total_entries,
            "exits": exits,
            "dropoff_rate": dropoff_rate,
            "conversion_to_next_rate": conversion_to_next,
            "avg_time_seconds": avg_node_time,
        })

    top_dropoffs = sorted(funnel, key=lambda item: item["dropoff_rate"], reverse=True)[:5]

    total_replies = sum(reply_counter.values())
    common_replies = [
        {"reply": reply, "count": count, "rate": _safe_rate(count, total_replies)}
        for reply, count in reply_counter.most_common(8)
    ]

    timeline = [
        {
            "date": (row.dt if isinstance(row.dt, date) else row.dt.date()).isoformat(),
            "entries": int(row.entries or 0),
            "messages_sent": int(row.messages_sent or 0),
            "completed": int(row.completed or 0),
        }
        for row in timeline_rows
    ]

    summary = {
        "entries": entries,
        "messages": messages_sent,
        "messages_sent": messages_sent,
        "completed": completed,
        "conversion_rate": _safe_rate(completed, entries),
        "dropoff_rate": _safe_rate(abandoned, entries),
        "avg_time": avg_time_seconds,
        "avg_time_seconds": avg_time_seconds,
        "avg_messages_per_user": avg_messages_per_user,
    }

    insights: list[dict[str, Any]] = []
    if summary["dropoff_rate"] > 40:
        worst = top_dropoffs[0] if top_dropoffs else None
        insights.append({"type": "warning", "title": "Alto abandono", "message": "Este flow perde muitos usuários em pontos críticos.", "node_id": worst["node_id"] if worst else None})
    if summary["conversion_rate"] < 20 and summary["entries"] > 0:
        insights.append({"type": "warning", "title": "Baixa conversão", "message": "A taxa de conclusão está abaixo de 20%. Revise conteúdo e decisões.", "node_id": None})
    if summary["avg_time_seconds"] > 180:
        insights.append({"type": "info", "title": "Sinal de fricção", "message": "O tempo médio está elevado. Pode haver etapas longas ou confusas.", "node_id": None})
    if summary["conversion_rate"] >= 60 and summary["entries"] > 0:
        insights.append({"type": "success", "title": "Flow saudável", "message": "Boa taxa de conclusão no período analisado.", "node_id": None})

    base.update({"summary": summary, "funnel": funnel, "top_dropoffs": top_dropoffs, "common_replies": common_replies, "timeline": timeline or None, "insights": insights or None})
    return base


def record_flow_event(db: Session, *, tenant_id: uuid.UUID, conversation_id: uuid.UUID, flow_id: uuid.UUID | None, flow_version_id: uuid.UUID | None, node_id: uuid.UUID | None, event_type: str, user_id: str | None = None, metadata: dict[str, Any] | None = None) -> None:
    if event_type not in VALID_EVENT_TYPES:
        logger.warning("event=flow_event_skip reason=invalid_type event_type=%s", event_type)
        return
    db.add(FlowEvent(tenant_id=tenant_id, conversation_id=conversation_id, flow_id=flow_id, flow_version_id=flow_version_id, node_id=node_id, event_type=event_type, user_id=user_id, metadata_json=metadata or {}))
