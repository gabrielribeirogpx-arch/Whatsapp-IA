from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models import Contact, Conversation, Lead, Message, Product, Tenant
from app.services.tenant_service import get_current_tenant

router = APIRouter(tags=["dashboard"])


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
        select(func.count(Lead.id)).where(Lead.tenant_id == tenant.id)
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
            Lead.created_at >= start_datetime,
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
        select(func.count(Lead.id)).where(
            Lead.tenant_id == tenant.id,
            Lead.stage == "fechado",
            Lead.created_at >= start_datetime,
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

    return DashboardAnalyticsOut(
        kpis=DashboardAnalyticsKpisOut(
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
