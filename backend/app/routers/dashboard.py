from datetime import date, datetime, time, timedelta

import asyncio
import logging
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.db.session import SessionLocal, get_db
from app.models import AuditLog, Contact, Conversation, Flow, FlowEvent, FlowSession, Lead, Message, PipelineStage, Product, Tenant
from app.models.lead import LeadStatus
from app.services.dashboard_time import (
    iter_daily_buckets,
    percentage_delta,
    resolve_dashboard_time_range,
)
from app.services.realtime_service import sse_broker
from app.services.websocket_auth import authenticate_ws_user
from app.services.tenant_service import get_current_tenant

router = APIRouter(tags=["dashboard"])

logger = logging.getLogger(__name__)


def _dashboard_date_range(period: str, start_date: date | None, end_date: date | None) -> tuple[datetime, datetime, int]:
    """Backward-compatible adapter; new code should use the canonical resolver."""
    window = resolve_dashboard_time_range(period, start_date, end_date)
    return window.current_start, window.current_end, window.bucket_count


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
    messages_sent_current: int
    messages_received_current: int
    messages_sent_previous: int
    messages_received_previous: int
    messages_delta: float | None


class DashboardTimeMetaOut(BaseModel):
    current_start: datetime
    current_end: datetime
    previous_start: datetime
    previous_end: datetime
    timezone: str
    mode: str


class DashboardAnalyticsTimeseriesOut(BaseModel):
    messages_last_7_days: list[MessagesByDay]


class DashboardAnalyticsOut(BaseModel):
    kpis: DashboardAnalyticsKpisOut
    timeseries: DashboardAnalyticsTimeseriesOut
    meta: DashboardTimeMetaOut | None = None


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
    contact_name: str | None = None
    phone: str | None = None
    created_at: datetime


def _activity_from_audit_log(row: AuditLog) -> DashboardActivityOut:
    metadata = row.metadata_json or {}
    phone = str(metadata.get("phone") or "").strip() or None
    contact_name = str(metadata.get("contact_name") or metadata.get("name") or "").strip() or None
    display_name = contact_name or phone
    titles = {
        "LEAD_CREATED": "Novo lead criado",
        "LEAD_MOVED": "Lead movido de etapa",
        "LEAD_CONVERTED": "Lead concluído",
        "LEAD_DELETED": "Lead removido",
        "CONVERSATION_STARTED": "Nova conversa iniciada",
    }
    title = str(metadata.get("event") or titles.get(row.action, row.action))
    if display_name and row.action in {"LEAD_CREATED", "CONVERSATION_STARTED"}:
        title = f"{title}: {display_name}"
    return DashboardActivityOut(
        id=str(row.id),
        type=row.action,
        title=title,
        description=str(metadata.get("phone") or metadata.get("to_stage") or "") or None,
        entity_type=row.entity_type,
        entity_id=row.entity_id,
        contact_name=contact_name,
        phone=phone,
        created_at=row.created_at,
    )


class DashboardSummaryOut(BaseModel):
    top_flows: list[DashboardTopFlowOut]
    channels: list[DashboardChannelOut]
    performance: DashboardPerformanceOut
    meta: DashboardTimeMetaOut | None = None


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
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    try:
        window = resolve_dashboard_time_range(period, start_date, end_date, now=datetime.utcnow())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    start_datetime, end_datetime = window.current_start, window.current_end
    conversations_total = db.execute(
        select(func.count(Conversation.id)).where(
            Conversation.tenant_id == tenant.id,
            Conversation.updated_at.isnot(None),
            Conversation.updated_at >= start_datetime,
            Conversation.updated_at < end_datetime,
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
            Message.created_at < end_datetime,
        )
    ).scalar() or 0

    messages_sent_period = db.execute(
        select(func.count(Message.id)).where(
            Message.tenant_id == tenant.id,
            Message.from_me.is_(True),
            Message.created_at.isnot(None),
            Message.created_at >= start_datetime,
            Message.created_at < end_datetime,
        )
    ).scalar() or 0

    messages_received_period = db.execute(
        select(func.count(Message.id)).where(
            Message.tenant_id == tenant.id,
            Message.from_me.is_(False),
            Message.created_at.isnot(None),
            Message.created_at >= start_datetime,
            Message.created_at < end_datetime,
        )
    ).scalar() or 0

    messages_sent_previous = db.execute(
        select(func.count(Message.id)).where(
            Message.tenant_id == tenant.id,
            Message.from_me.is_(True),
            Message.created_at.isnot(None),
            Message.created_at >= window.previous_start,
            Message.created_at < window.previous_end,
        )
    ).scalar() or 0
    messages_received_previous = db.execute(
        select(func.count(Message.id)).where(
            Message.tenant_id == tenant.id,
            Message.from_me.is_(False),
            Message.created_at.isnot(None),
            Message.created_at >= window.previous_start,
            Message.created_at < window.previous_end,
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
    for start_of_target_day, end_of_target_day in iter_daily_buckets(window):

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

    current_messages = messages_sent_period + messages_received_period
    previous_messages = messages_sent_previous + messages_received_previous
    logger.debug(
        "dashboard_analytics_window tenant_id=%s current_start=%s current_end=%s previous_start=%s previous_end=%s current_messages=%s previous_messages=%s",
        tenant.id, window.current_start, window.current_end, window.previous_start,
        window.previous_end, current_messages, previous_messages,
    )
    return DashboardAnalyticsOut(
        kpis=DashboardAnalyticsKpisOut(
            active_conversations=conversations_total,
            active_leads=leads_total,
            messages_today=current_messages,
            conversations=conversations_total,
            contacts=contacts_total,
            leads=leads_total,
            products=products_total,
            messages=messages_total,
            conversations_updated_today=conversations_total,
            messages_sent_today=messages_sent_period,
            messages_received_today=messages_received_period,
            conversions=conversions_total,
            messages_sent_current=messages_sent_period,
            messages_received_current=messages_received_period,
            messages_sent_previous=messages_sent_previous,
            messages_received_previous=messages_received_previous,
            messages_delta=percentage_delta(current_messages, previous_messages),
        ),
        timeseries=DashboardAnalyticsTimeseriesOut(
            messages_last_7_days=messages_last_7_days,
        ),
        meta=DashboardTimeMetaOut(**window.__dict__),
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
    print("[LIVE ACTIVITY]", f"tenant_id={tenant.id}", f"count={len(rows)}")
    return [_activity_from_audit_log(row) for row in rows]


@router.get("/dashboard/stream")
async def stream_dashboard_events(
    tenant: Tenant = Depends(get_current_tenant),
):
    channel = f"dashboard:{tenant.id}"
    queue = await sse_broker.subscribe(channel)

    async def event_generator():
        try:
            while True:
                try:
                    data = await asyncio.wait_for(queue.get(), timeout=20)
                    yield data
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            sse_broker.unsubscribe(channel, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.websocket("/dashboard/ws")
async def ws_dashboard_events(websocket: WebSocket):
    print("[WS HANDSHAKE START]")
    try:
        tenant_id_raw = str(websocket.query_params.get("tenant_id") or "").strip()
        token = str(websocket.query_params.get("token") or "").strip()
        try:
            from uuid import UUID

            tenant_id = UUID(tenant_id_raw)
        except ValueError:
            await websocket.close(code=1008)
            return

        db = SessionLocal()
        try:
            authenticate_ws_user(db, tenant_id, token)
            print("[WS CONNECTED DASHBOARD]", tenant_id)
            channel = f"dashboard:{tenant_id}"
            await websocket.accept()
            await sse_broker.subscribe_websocket(channel, websocket)
            try:
                while True:
                    await websocket.receive_text()
            except WebSocketDisconnect:
                pass
            finally:
                sse_broker.unsubscribe_websocket(channel, websocket)
        finally:
            db.close()
    except Exception as e:
        print("[WS ERROR]", repr(e))
        raise


@router.get("/dashboard/summary", response_model=DashboardSummaryOut)
def get_dashboard_summary(
    period: str = Query(default="7d"),
    start_date: date | None = Query(default=None),
    end_date: date | None = Query(default=None),
    db: Session = Depends(get_db),
    tenant: Tenant = Depends(get_current_tenant),
):
    try:
        window = resolve_dashboard_time_range(period, start_date, end_date, now=datetime.utcnow())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    start_datetime, end_datetime = window.current_start, window.current_end
    flow_rows = db.execute(
        select(
            FlowEvent.flow_id,
            func.count(func.distinct(FlowEvent.conversation_id)).label("conversations"),
            func.sum(case((FlowEvent.event_type.in_(["FLOW_COMPLETED", "flow_completed", "FLOW_FINISH", "CONVERSION"]), 1), else_=0)).label("completed"),
        )
        .where(
            FlowEvent.tenant_id == tenant.id,
            FlowEvent.created_at >= start_datetime,
            FlowEvent.created_at < end_datetime,
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
        completed = int(getattr(row, "completed", 0) or 0)
        top_flows.append(DashboardTopFlowOut(
            flow_id=str(row.flow_id),
            name=flow_names.get(row.flow_id, "Fluxo"),
            conversations=conversations,
            conversion_rate=round((completed / conversations) * 100, 2) if conversations else 0,
        ))

    conversations = db.execute(
        select(Conversation.context)
        .where(Conversation.tenant_id == tenant.id, Conversation.updated_at.isnot(None), Conversation.updated_at >= start_datetime, Conversation.updated_at < end_datetime)
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
            FlowSession.updated_at < end_datetime,
            FlowSession.status.in_(["completed", "converted", "conversion"]),
        )
    ).scalar() or 0

    started_sessions = db.execute(
        select(func.count(FlowSession.id)).where(FlowSession.tenant_id == tenant.id, FlowSession.created_at >= start_datetime, FlowSession.created_at < end_datetime)
    ).scalar() or 0
    abandoned_sessions = db.execute(
        select(func.count(FlowSession.id)).where(
            FlowSession.tenant_id == tenant.id,
            FlowSession.updated_at >= start_datetime,
            FlowSession.updated_at < end_datetime,
            FlowSession.status.in_(["abandoned", "expired"]),
        )
    ).scalar() or 0
    abandonment_rate = round((abandoned_sessions / started_sessions) * 100, 2) if started_sessions > 0 else 0

    response_pairs = db.execute(
        select(Message.conversation_id, Message.created_at, Message.from_me)
        .where(Message.tenant_id == tenant.id, Message.created_at >= start_datetime, Message.created_at < end_datetime)
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
        meta=DashboardTimeMetaOut(**window.__dict__),
    )
