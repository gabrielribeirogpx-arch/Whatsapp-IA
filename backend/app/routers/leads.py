import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Lead, PipelineStage, Tenant
from app.models.lead import LeadStage
from app.schemas.lead import (
    LeadMoveRequest,
    LeadOut,
    LeadStageUpdateRequest,
    LeadStatsOut,
    PipelineLeadOut,
    PipelineStageOut,
)
from app.services.pipeline_service import ensure_pipeline_stages
from app.services.tenant_service import get_current_tenant

router = APIRouter(tags=["leads"])


class PipelineStageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    position: int | None = Field(default=None, ge=0)


class PipelineStageUpdate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    position: int = Field(ge=0)


def _get_stage_or_404(db: Session, tenant_id: uuid.UUID, stage_id: uuid.UUID) -> PipelineStage:
    stage = db.execute(
        select(PipelineStage).where(
            PipelineStage.id == stage_id,
            PipelineStage.tenant_id == tenant_id,
        )
    ).scalars().first()
    if not stage:
        raise HTTPException(status_code=404, detail="Etapa do pipeline não encontrada")
    return stage


@router.get("/leads", response_model=list[LeadOut])
def list_leads(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    return (
        db.execute(
            select(Lead)
            .where(Lead.tenant_id == tenant.id)
            .order_by(desc(Lead.last_contact_at), desc(Lead.id))
        )
        .scalars()
        .all()
    )


@router.patch("/leads/{lead_id}/stage", response_model=LeadOut)
def update_lead_stage(
    lead_id: uuid.UUID,
    payload: LeadStageUpdateRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    lead = db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant.id)
    ).scalars().first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead não encontrado")

    lead.stage = payload.stage.value
    print("PIPELINE_UPDATE:", str(lead_id), payload.stage.value)
    db.commit()
    db.refresh(lead)
    return lead


@router.get("/pipeline", response_model=list[PipelineStageOut])
def get_pipeline(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    stages = ensure_pipeline_stages(db, tenant.id)

    leads = (
        db.execute(
            select(Lead)
            .where(Lead.tenant_id == tenant.id)
            .order_by(desc(Lead.score), desc(Lead.last_interaction), desc(Lead.created_at))
        )
        .scalars()
        .all()
    )

    grouped: dict[uuid.UUID, list[PipelineLeadOut]] = {stage.id: [] for stage in stages}
    fallback_stage_id = stages[0].id if stages else None

    for lead in leads:
        target_stage_id = lead.stage_id or fallback_stage_id
        if not target_stage_id:
            continue
        if target_stage_id not in grouped:
            grouped[target_stage_id] = []
        grouped[target_stage_id].append(PipelineLeadOut.model_validate(lead))

    return [
        PipelineStageOut(
            id=stage.id,
            name=stage.name,
            position=stage.position,
            leads=grouped.get(stage.id, []),
        )
        for stage in sorted(stages, key=lambda item: item.position)
    ]


@router.post("/pipeline", response_model=PipelineStageOut)
def create_pipeline_stage(
    payload: PipelineStageCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    ensure_pipeline_stages(db, tenant.id)
    position = payload.position
    if position is None:
        position = db.execute(
            select(func.coalesce(func.max(PipelineStage.position), -1)).where(PipelineStage.tenant_id == tenant.id)
        ).scalar_one() + 1

    stage = PipelineStage(tenant_id=tenant.id, name=payload.name.strip(), position=position)
    db.add(stage)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Já existe uma etapa com este nome ou posição") from exc
    db.refresh(stage)
    return PipelineStageOut(id=stage.id, name=stage.name, position=stage.position, leads=[])


@router.put("/pipeline/{stage_id}", response_model=PipelineStageOut)
def update_pipeline_stage(
    stage_id: uuid.UUID,
    payload: PipelineStageUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    stage = _get_stage_or_404(db, tenant.id, stage_id)
    stage.name = payload.name.strip()
    stage.position = payload.position
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Já existe uma etapa com este nome ou posição") from exc
    db.refresh(stage)
    return PipelineStageOut(id=stage.id, name=stage.name, position=stage.position, leads=[])


@router.delete("/pipeline/{stage_id}")
def delete_pipeline_stage(
    stage_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    stages = ensure_pipeline_stages(db, tenant.id)
    stage = _get_stage_or_404(db, tenant.id, stage_id)
    fallback = next((item for item in stages if item.id != stage.id), None)
    lead_count = db.execute(
        select(func.count(Lead.id)).where(Lead.tenant_id == tenant.id, Lead.stage_id == stage.id)
    ).scalar_one()
    if lead_count and not fallback:
        raise HTTPException(status_code=409, detail="Não é possível remover a única etapa com leads")
    if fallback:
        leads = db.execute(
            select(Lead).where(Lead.tenant_id == tenant.id, Lead.stage_id == stage.id)
        ).scalars().all()
        for lead in leads:
            lead.stage_id = fallback.id
    db.delete(stage)
    db.commit()
    return {"deleted": True}


@router.post("/leads/{lead_id}/move", response_model=LeadOut)
def move_lead(
    lead_id: uuid.UUID,
    payload: LeadMoveRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    lead = db.execute(
        select(Lead).where(Lead.id == lead_id, Lead.tenant_id == tenant.id)
    ).scalars().first()
    if not lead:
        raise HTTPException(status_code=404, detail="Lead não encontrado")

    target_stage = db.execute(
        select(PipelineStage).where(PipelineStage.id == payload.stage_id, PipelineStage.tenant_id == tenant.id)
    ).scalars().first()
    if not target_stage:
        raise HTTPException(status_code=404, detail="Stage não encontrado")

    lead.stage_id = target_stage.id

    db.commit()
    db.refresh(lead)
    return lead


@router.get("/leads/stats", response_model=LeadStatsOut)
def leads_stats(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    total = db.execute(
        select(func.count(Lead.id)).where(Lead.tenant_id == tenant.id)
    ).scalar_one()

    rows = db.execute(
        select(Lead.stage, func.count(Lead.id))
        .where(Lead.tenant_id == tenant.id)
        .group_by(Lead.stage)
    ).all()

    by_stage = {stage: 0 for stage in LeadStage}
    for stage, count in rows:
        try:
            by_stage[LeadStage(stage)] = count
        except ValueError:
            continue

    return LeadStatsOut(total=total, por_stage=by_stage)
