from datetime import datetime, timedelta

import logging
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import AuditLog, Contact, Conversation, Flow, FlowEvent, FlowSession, Lead, Message, PipelineStage, Product, Tenant
from app.models.lead import LeadStatus
from app.services.tenant_service import get_current_tenant

router = APIRouter(tags=["dashboard"])

logger = logging.getLogger(__name__)


class DashboardTotalsOut(BaseModel):
    conversations: int
    contacts: int
    leads: int
    products: int
    messages: int


class DashboardTodayOut(BaseModel):
    conversations_updated: int
    messages_sent: int
    messages_received: int


class MessagesByDay(BaseModel):
    date: str
    sent: int
    received: int


class DashboardChartsOut(BaseModel):
    messages_last_7_days: list[MessagesByDay]


class DashboardOut(BaseModel):
    tenant_id: str
    totals: DashboardTotalsOut
    today: DashboardTodayOut
    charts: DashboardChartsOut


class DashboardAnalyticsKpisOut(BaseModel):
    active_conversations: int
    active_leads: int
    messages_today: int
    conversations: int
    contacts: int
    leads: int
    products: int
    messages: int
    conversations_updated_today: int
    messages_sent_today: int
    messages_received_today: int
    conversions: int


class DashboardAnalyticsTimeseriesOut(BaseModel):
    messages_last_7_days: list[MessagesByDay]


class DashboardAnalyticsOut(BaseModel):
    kpis: DashboardAnalyticsKpisOut
    timeseries: DashboardAnalyticsTimeseriesOut


class DashboardTopFlowOut(BaseModel):
    flow_id: str
    name: str
    conversations: int
    conversion_rate: float


class DashboardChannelOut(BaseModel):
    channel: str
    count: int
    percentage: float


class DashboardPerformanceOut(BaseModel):
    avg_response_time_seconds: float | None
    resolved_conversations: int
    csat: float | None
    abandonment_rate: float




class DashboardActivityOut(BaseModel):
    id: str
    type: str
    title: str
    description: str | None = None
    entity_type: str | None = None
    entity_id: str | None = None
    created_at: datetime


class DashboardSummaryOut(BaseModel):
    top_flows: list[DashboardTopFlowOut]
    channels: list[DashboardChannelOut]
    performance: DashboardPerformanceOut


@router.get("/dashboard", response_model=DashboardOut)
def get_dashboard(
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    now_utc = datetime.utcnow()
    start_of_day = datetime(now_utc.year, now_utc.month, now_utc.day)

    conversations_total = db.execute(
        select(func.count(Conversation.id)).where(Conversation.tenant_id == tenant.id)
    ).scalar() or 0

    contacts_total = db.execute(
        select(func.count(Contact.id)).where(Contact.tenant_id == tenant.id)
    ).scalar() or 0

    leads_total = db.execute(
        select(func.count(Lead.id)).where(Lead.tenant_id == tenant.id, Lead.status == LeadStatus.ACTIVE.value)
    ).scalar() or 0

    products_total = db.execute(
        select(func.count(Product.id)).where(Product.tenant_id == tenant.id)
    ).scalar() or 0

    messages_total = db.execute(
        select(func.count(Message.id)).where(
            Message.tenant_id == tenant.id,
            Message.created_at.isnot(None),
        )
    ).scalar() or 0

    conversations_updated_today = db.execute(
        select(func.count(Conversation.id)).where(
            Conversation.tenant_id == tenant.id,
            Conversation.updated_at.isnot(None),
            Conversation.updated_at >= start_of_day,
        )
    ).scalar() or 0

    messages_sent_today = db.execute(
        select(func.count(Message.id)).where(
            Message.tenant_id == tenant.id,
            Message.from_me.is_(True),
            Message.created_at.isnot(None),
            Message.created_at >= start_of_day,
        )
    ).scalar() or 0

    messages_received_today = db.execute(
        select(func.count(Message.id)).where(
            Message.tenant_id == tenant.id,
            Message.from_me.is_(False),
            Message.created_at.isnot(None),
            Message.created_at >= start_of_day,
        )
    ).scalar() or 0

    messages_last_7_days: list[MessagesByDay] = []
    for day_offset in range(6, -1, -1):
        target_day = now_utc - timedelta(days=day_offset)
        start_of_target_day = datetime(target_day.year, target_day.month, target_day.day)
        end_of_target_day = start_of_target_day + timedelta(days=1)

        sent_count = db.execute(
            select(func.count(Message.id)).where(
                Message.tenant_id == tenant.id,
                Message.from_me.is_(True),
                Message.created_at.isnot(None),
                Message.created_at >= start_of_target_day,
                Message.created_at < end_of_target_day,
            )
        ).scalar() or 0

        received_count = db.execute(
            select(func.count(Message.id)).where(
                Message.tenant_id == tenant.id,
                Message.from_me.is_(False),
                Message.created_at.isnot(None),
                Message.created_at >= start_of_target_day,
                Message.created_at < end_of_target_day,
            )
        ).scalar() or 0

        messages_last_7_days.append(
            MessagesByDay(
                date=start_of_target_day.strftime("%Y-%m-%d"),
                sent=sent_count,
                received=received_count,
            )
        )

    return DashboardOut(
        tenant_id=str(tenant.id),
        totals=DashboardTotalsOut(
            active_conversations=conversations_total,
            active_leads=leads_total,
            messages_today=messages_sent_period + messages_received_period,
            conversations=conversations_total,
            contacts=contacts_total,
            leads=leads_total,
            products=products_total,
            messages=messages_total,
        ),
        today=DashboardTodayOut(
            conversations_updated=conversations_updated_today,
            messages_sent=messages_sent_today,
            messages_received=messages_received_today,
        ),
        charts=DashboardChartsOut(messages_last_7_days=messages_last_7_days),
    )


@router.get("/dashboard/analytics", response_model=DashboardAnalyticsOut)
def get_dashboard_analytics(
    period: str = Query(default="7d"),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    period_to_days = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}
    days = period_to_days.get(period, 7)

    now_utc = datetime.utcnow()
    start_datetime = now_utc - timedelta(days=days)

    conversations_total = db.execute(
        select(func.count(Conversation.id)).where(
            Conversation.tenant_id == tenant.id,
            Conversation.updated_at.isnot(None),
            Conversation.updated_at >= start_datetime,
        )
    ).scalar() or 0

    contacts_total = db.execute(
        select(func.count(Contact.id)).where(
            Contact.tenant_id == tenant.id,
        )
    ).scalar() or 0

    leads_total = db.execute(
        select(func.count(Lead.id)).where(
            Lead.tenant_id == tenant.id,
            Lead.status == LeadStatus.ACTIVE.value,
        )
    ).scalar() or 0

    products_total = db.execute(
        select(func.count(Product.id)).where(Product.tenant_id == tenant.id)
    ).scalar() or 0

    messages_total = db.execute(
        select(func.count(Message.id)).where(
            Message.tenant_id == tenant.id,
            Message.created_at.isnot(None),
            Message.created_at >= start_datetime,
        )
    ).scalar() or 0

    messages_sent_period = db.execute(
        select(func.count(Message.id)).where(
            Message.tenant_id == tenant.id,
            Message.from_me.is_(True),
            Message.created_at.isnot(None),
            Message.created_at >= start_datetime,
        )
    ).scalar() or 0

    messages_received_period = db.execute(
        select(func.count(Message.id)).where(
            Message.tenant_id == tenant.id,
            Message.from_me.is_(False),
            Message.created_at.isnot(None),
            Message.created_at >= start_datetime,
        )
    ).scalar() or 0

    conversions_total = db.execute(
        select(func.count(Lead.id))
        .join(PipelineStage, Lead.stage_id == PipelineStage.id)
        .where(
            Lead.tenant_id == tenant.id,
            PipelineStage.tenant_id == tenant.id,
            PipelineStage.is_final_stage.is_(True),
        )
    ).scalar() or 0

    messages_last_7_days: list[MessagesByDay] = []
    for day_offset in range(days - 1, -1, -1):
        target_day = now_utc - timedelta(days=day_offset)
        start_of_target_day = datetime(target_day.year, target_day.month, target_day.day)
        end_of_target_day = start_of_target_day + timedelta(days=1)

        sent_count = db.execute(
            select(func.count(Message.id)).where(
                Message.tenant_id == tenant.id,
                Message.from_me.is_(True),
                Message.created_at.isnot(None),
                Message.created_at >= start_of_target_day,
                Message.created_at < end_of_target_day,
            )
        ).scalar() or 0

        received_count = db.execute(
            select(func.count(Message.id)).where(
                Message.tenant_id == tenant.id,
                Message.from_me.is_(False),
                Message.created_at.isnot(None),
                Message.created_at >= start_of_target_day,
                Message.created_at < end_of_target_day,
            )
        ).scalar() or 0

        messages_last_7_days.append(
            MessagesByDay(
                date=start_of_target_day.strftime("%Y-%m-%d"),
                sent=sent_count,
                received=received_count,
            )
        )

    print("[DASHBOARD METRICS]", f"tenant_id={tenant.id}", f"active_conversations={conversations_total}", f"active_leads={leads_total}", f"messages_today={messages_sent_period + messages_received_period}", f"conversions={conversions_total}")
    return DashboardAnalyticsOut(
        kpis=DashboardAnalyticsKpisOut(
            active_conversations=conversations_total,
            active_leads=leads_total,
            messages_today=messages_sent_period + messages_received_period,
            conversations=conversations_total,
            contacts=contacts_total,
            leads=leads_total,
            products=products_total,
            messages=messages_total,
            conversations_updated_today=conversations_total,
            messages_sent_today=messages_sent_period,
            messages_received_today=messages_received_period,
            conversions=conversions_total,
        ),
        timeseries=DashboardAnalyticsTimeseriesOut(
            messages_last_7_days=messages_last_7_days,
        ),
    )


@router.get("/dashboard/activity", response_model=list[DashboardActivityOut])
def get_dashboard_activity(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    actions = ["LEAD_CREATED", "LEAD_MOVED", "LEAD_CONVERTED", "LEAD_DELETED", "CONVERSATION_STARTED"]
    rows = (
        db.execute(
            select(AuditLog)
            .where(AuditLog.tenant_id == tenant.id, AuditLog.action.in_(actions))
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    titles = {
        "LEAD_CREATED": "Novo lead criado",
        "LEAD_MOVED": "Lead movido de etapa",
        "LEAD_CONVERTED": "Lead concluído",
        "LEAD_DELETED": "Lead removido",
        "CONVERSATION_STARTED": "Nova conversa iniciada",
    }
    print("[LIVE ACTIVITY]", f"tenant_id={tenant.id}", f"count={len(rows)}")
    return [
        DashboardActivityOut(
            id=str(row.id),
            type=row.action,
            title=str((row.metadata_json or {}).get("event") or titles.get(row.action, row.action)),
            description=str((row.metadata_json or {}).get("phone") or (row.metadata_json or {}).get("to_stage") or "") or None,
            entity_type=row.entity_type,
            entity_id=row.entity_id,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/dashboard/summary", response_model=DashboardSummaryOut)
def get_dashboard_summary(
    period: str = Query(default="7d"),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    period_to_days = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}
    days = period_to_days.get(period, 7)
    now_utc = datetime.utcnow()
    start_datetime = now_utc - timedelta(days=days)

    flow_rows = db.execute(
        select(FlowEvent.flow_id, func.count(func.distinct(FlowEvent.conversation_id)).label("conversations"))
        .where(
            FlowEvent.tenant_id == tenant.id,
            FlowEvent.created_at >= start_datetime,
            FlowEvent.flow_id.isnot(None),
        )
        .group_by(FlowEvent.flow_id)
        .order_by(func.count(func.distinct(FlowEvent.conversation_id)).desc())
        .limit(5)
    ).all()

    flow_ids = [row.flow_id for row in flow_rows if row.flow_id is not None]
    flow_names = {}
    if flow_ids:
        for fid, name in db.execute(select(Flow.id, Flow.name).where(Flow.tenant_id == tenant.id, Flow.id.in_(flow_ids))).all():
            flow_names[fid] = name

    top_flows: list[DashboardTopFlowOut] = []
    for row in flow_rows:
        conversations = int(row.conversations or 0)
        top_flows.append(DashboardTopFlowOut(
            flow_id=str(row.flow_id),
            name=flow_names.get(row.flow_id, "Fluxo"),
            conversations=conversations,
            conversion_rate=0,
        ))

    conversations = db.execute(
        select(Conversation.context)
        .where(Conversation.tenant_id == tenant.id, Conversation.updated_at.isnot(None), Conversation.updated_at >= start_datetime)
    ).scalars().all()
    channel_counts = {"whatsapp": 0, "site_chat": 0, "instagram": 0, "facebook": 0, "outros": 0}
    for context in conversations:
        raw_channel = ""
        if isinstance(context, dict):
            raw_channel = str(context.get("channel") or context.get("source") or "").strip().lower()
        if raw_channel in {"site", "site/chat", "site / chat", "site_chat"}:
            channel_counts["site_chat"] += 1
        elif raw_channel in {"instagram"}:
            channel_counts["instagram"] += 1
        elif raw_channel in {"facebook", "messenger"}:
            channel_counts["facebook"] += 1
        elif raw_channel in {"whatsapp", "wa"}:
            channel_counts["whatsapp"] += 1
        else:
            channel_counts["outros"] += 1 if raw_channel else 0

    total_channels = sum(channel_counts.values())
    channels: list[DashboardChannelOut] = []
    if total_channels > 0:
        for channel, count in channel_counts.items():
            if count <= 0:
                continue
            channels.append(DashboardChannelOut(channel=channel, count=count, percentage=round((count / total_channels) * 100, 2)))

    resolved_conversations = db.execute(
        select(func.count(func.distinct(FlowSession.conversation_id))).where(
            FlowSession.tenant_id == tenant.id,
            FlowSession.updated_at >= start_datetime,
            FlowSession.status.in_(["completed", "converted", "conversion"]),
        )
    ).scalar() or 0

    started_sessions = db.execute(
        select(func.count(FlowSession.id)).where(FlowSession.tenant_id == tenant.id, FlowSession.created_at >= start_datetime)
    ).scalar() or 0
    abandoned_sessions = db.execute(
        select(func.count(FlowSession.id)).where(
            FlowSession.tenant_id == tenant.id,
            FlowSession.updated_at >= start_datetime,
            FlowSession.status.in_(["abandoned", "expired"]),
        )
    ).scalar() or 0
    abandonment_rate = round((abandoned_sessions / started_sessions) * 100, 2) if started_sessions > 0 else 0

    response_pairs = db.execute(
        select(Message.conversation_id, Message.created_at, Message.from_me)
        .where(Message.tenant_id == tenant.id, Message.created_at >= start_datetime)
        .order_by(Message.conversation_id, Message.created_at)
    ).all()
    total_delay = 0.0
    delay_count = 0
    last_inbound_by_conversation = {}
    for conversation_id, created_at, from_me in response_pairs:
        if not created_at:
            continue
        if not from_me:
            last_inbound_by_conversation[conversation_id] = created_at
            continue
        inbound_at = last_inbound_by_conversation.get(conversation_id)
        if inbound_at is None:
            continue
        diff = (created_at - inbound_at).total_seconds()
        if diff >= 0:
            total_delay += diff
            delay_count += 1
        last_inbound_by_conversation.pop(conversation_id, None)

    avg_response_time_seconds = round(total_delay / delay_count, 2) if delay_count > 0 else None

    logger.info(
        "[DASHBOARD SUMMARY] tenant_id=%s period=%s top_flows_count=%s channels_count=%s",
        tenant.id,
        period,
        len(top_flows),
        len(channels),
    )

    return DashboardSummaryOut(
        top_flows=top_flows,
        channels=channels,
        performance=DashboardPerformanceOut(
            avg_response_time_seconds=avg_response_time_seconds,
            resolved_conversations=int(resolved_conversations),
            csat=None,
            abandonment_rate=abandonment_rate,
        ),
    )
