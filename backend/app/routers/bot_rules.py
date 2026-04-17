from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import BotRule, Tenant
from app.schemas.bot_rule import BotRuleCreate, BotRuleOut
from app.services.tenant_service import get_current_tenant

router = APIRouter(prefix="/api/bot/rules", tags=["bot-rules"])


@router.post("", response_model=BotRuleOut)
def create_bot_rule(
    payload: BotRuleCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    rule = BotRule(
        tenant_id=tenant.id,
        trigger=payload.trigger.strip(),
        response=payload.response.strip(),
        match_type=payload.match_type,
    )
    db.add(rule)
    db.commit()
    db.refresh(rule)
    return rule


@router.get("", response_model=list[BotRuleOut])
def list_bot_rules(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    return (
        db.execute(
            select(BotRule)
            .where(BotRule.tenant_id == tenant.id)
            .order_by(BotRule.created_at.desc(), BotRule.id.desc())
        )
        .scalars()
        .all()
    )


@router.delete("/{rule_id}")
def delete_bot_rule(
    rule_id: UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    rule = db.execute(select(BotRule).where(BotRule.id == rule_id, BotRule.tenant_id == tenant.id)).scalars().first()
    if not rule:
        raise HTTPException(status_code=404, detail="Regra não encontrada")

    db.delete(rule)
    db.commit()
    return {"deleted": True}
