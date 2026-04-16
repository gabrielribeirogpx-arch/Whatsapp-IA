from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.base import get_db
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


class DashboardOut(BaseModel):
    tenant_id: str
    totals: DashboardTotalsOut
    today: DashboardTodayOut


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
        select(func.count(Message.id)).where(Message.tenant_id == tenant.id)
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
    )
