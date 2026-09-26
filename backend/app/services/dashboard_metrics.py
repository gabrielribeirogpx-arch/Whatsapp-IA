"""Canonical, tenant-scoped calculations for dashboard business metrics.

Time windows are half-open (``start <= timestamp < end``).  Cohort metrics keep
their denominator tied to the event that entered the cohort, rather than mixing
events from unrelated windows.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, aliased

from app.models import Conversation, Flow, FlowEvent, FlowSession, Lead, Message
from app.models.lead import LeadStatus
from app.services.dashboard_time import percentage_delta


def get_moved_conversations(db: Session, tenant_id: Any, start: datetime, end: datetime) -> int:
    """Conversations whose last mutation belongs to the selected window."""
    return int(db.execute(select(func.count(Conversation.id)).where(
        Conversation.tenant_id == tenant_id,
        Conversation.updated_at.isnot(None),
        Conversation.updated_at >= start,
        Conversation.updated_at < end,
    )).scalar() or 0)


def get_active_leads(db: Session, tenant_id: Any) -> int:
    """Current snapshot; deliberately independent of the dashboard period."""
    return int(db.execute(select(func.count(Lead.id)).where(
        Lead.tenant_id == tenant_id,
        Lead.status == LeadStatus.ACTIVE.value,
    )).scalar() or 0)


def get_conversions(db: Session, tenant_id: Any, start: datetime, end: datetime) -> int:
    """Leads whose immutable first-conversion timestamp belongs to the window."""
    return int(db.execute(select(func.count(Lead.id)).where(
        Lead.tenant_id == tenant_id,
        Lead.converted_at >= start,
        Lead.converted_at < end,
    )).scalar() or 0)


def get_response_rate(db: Session, tenant_id: Any, start: datetime, end: datetime) -> tuple[float | None, int, int]:
    """Responded inbound conversations / inbound conversations.

    A response is any ``from_me`` message after an eligible inbound.  Message
    authorship does not currently distinguish a human from bot/AI. Replies are
    observed only before ``end``, freezing historical results at the period edge.
    """
    inbound = aliased(Message)
    outbound = aliased(Message)
    inbound_conversations = select(inbound.conversation_id).where(
        inbound.tenant_id == tenant_id,
        inbound.from_me.is_(False),
        inbound.created_at >= start,
        inbound.created_at < end,
    ).distinct().subquery()
    denominator = int(db.execute(select(func.count()).select_from(inbound_conversations)).scalar() or 0)
    responded = select(inbound.conversation_id).where(
        inbound.tenant_id == tenant_id,
        inbound.from_me.is_(False),
        inbound.created_at >= start,
        inbound.created_at < end,
        select(outbound.id).where(
            outbound.tenant_id == tenant_id,
            outbound.conversation_id == inbound.conversation_id,
            outbound.from_me.is_(True),
            outbound.created_at > inbound.created_at,
            outbound.created_at < end,
        ).exists(),
    ).distinct().subquery()
    numerator = int(db.execute(select(func.count()).select_from(responded)).scalar() or 0)
    rate = round((numerator / denominator) * 100, 2) if denominator else None
    return rate, numerator, denominator


def get_top_flows(db: Session, tenant_id: Any, start: datetime, end: datetime, limit: int = 5) -> list[dict[str, Any]]:
    rows = db.execute(
        select(FlowEvent.flow_id, Flow.name, func.count(func.distinct(FlowEvent.conversation_id)).label("conversation_count"))
        .join(Flow, Flow.id == FlowEvent.flow_id)
        .where(
            FlowEvent.tenant_id == tenant_id,
            Flow.tenant_id == tenant_id,
            FlowEvent.created_at >= start,
            FlowEvent.created_at < end,
            FlowEvent.flow_id.isnot(None),
        )
        .group_by(FlowEvent.flow_id, Flow.name)
        .order_by(func.count(func.distinct(FlowEvent.conversation_id)).desc(), Flow.name)
        .limit(limit)
    ).all()
    return [{"flow_id": str(row.flow_id), "name": row.name, "conversation_count": int(row.conversation_count)} for row in rows]


def _canonical_channel(context: Any) -> str:
    raw = str((context or {}).get("channel") or (context or {}).get("source") or "").strip().lower() if isinstance(context, dict) else ""
    if raw in {"site", "site/chat", "site / chat", "site_chat", "webchat"}:
        return "site_chat"
    if raw == "instagram":
        return "instagram"
    if raw in {"facebook", "messenger"}:
        return "facebook"
    if raw in {"whatsapp", "wa"}:
        return "whatsapp"
    return "outros"


def get_channel_distribution(db: Session, tenant_id: Any, start: datetime, end: datetime) -> tuple[list[dict[str, Any]], int]:
    contexts = db.execute(select(Conversation.context).where(
        Conversation.tenant_id == tenant_id,
        Conversation.updated_at.isnot(None),
        Conversation.updated_at >= start,
        Conversation.updated_at < end,
    )).scalars().all()
    counts: dict[str, int] = {}
    for context in contexts:
        channel = _canonical_channel(context)
        counts[channel] = counts.get(channel, 0) + 1
    total = len(contexts)
    items = [{"channel": channel, "count": count, "percentage": round(count / total * 100, 2)} for channel, count in counts.items()]
    return items, total


def response_cycle_delays(rows: list[tuple[Any, datetime, bool]], start: datetime, end: datetime) -> list[float]:
    """Return delays for first-inbound/first-response cycles initiated in window."""
    pending: dict[Any, datetime] = {}
    delays: list[float] = []
    for conversation_id, created_at, from_me in rows:
        if from_me and created_at < end:
            inbound_at = pending.pop(conversation_id, None)
            if inbound_at is not None and created_at > inbound_at:
                delays.append((created_at - inbound_at).total_seconds())
        elif start <= created_at < end and conversation_id not in pending:
            pending[conversation_id] = created_at
    return delays


def get_average_response_time(db: Session, tenant_id: Any, start: datetime, end: datetime) -> tuple[float | None, int]:
    rows = db.execute(select(Message.conversation_id, Message.created_at, Message.from_me).where(
        Message.tenant_id == tenant_id,
        Message.created_at >= start,
        Message.created_at < end,
    ).order_by(Message.conversation_id, Message.created_at, Message.id)).all()
    delays = response_cycle_delays(rows, start, end)
    return (round(sum(delays) / len(delays), 2), len(delays)) if delays else (None, 0)


def get_completed_sessions(db: Session, tenant_id: Any, start: datetime, end: datetime) -> int:
    return int(db.execute(select(func.count(FlowSession.id)).where(
        FlowSession.tenant_id == tenant_id,
        FlowSession.status == "completed",
        FlowSession.completed_at >= start,
        FlowSession.completed_at < end,
    )).scalar() or 0)


def get_abandonment_rate(db: Session, tenant_id: Any, start: datetime, end: datetime) -> tuple[float | None, int, int]:
    """Final observed abandoned/expired status among sessions created in window.

    Open sessions remain in the denominator.  This makes the cohort explicit and
    ensures the numerator is always a subset of the denominator.
    """
    denominator = int(db.execute(select(func.count(FlowSession.id)).where(
        FlowSession.tenant_id == tenant_id,
        FlowSession.created_at >= start,
        FlowSession.created_at < end,
    )).scalar() or 0)
    numerator = int(db.execute(select(func.count(FlowSession.id)).where(
        FlowSession.tenant_id == tenant_id,
        FlowSession.created_at >= start,
        FlowSession.created_at < end,
        FlowSession.status.in_(["abandoned", "expired"]),
    )).scalar() or 0)
    return (round(numerator / denominator * 100, 2) if denominator else None, numerator, denominator)


def metric_delta(current: float | int | None, previous: float | int | None) -> float | None:
    if current is None or previous is None:
        return None
    return percentage_delta(current, previous)
