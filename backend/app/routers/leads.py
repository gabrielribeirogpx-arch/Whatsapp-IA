import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Lead, PipelineStage, Tenant
from app.models.lead import LeadStage, LeadStatus
from app.schemas.lead import (
    LeadMoveRequest,
    LeadOut,
    LeadStageUpdateRequest,
    LeadStatsOut,
    PipelineLeadOut,
    PipelineStageOut,
)
from app.services.audit_service import write_audit_log
from app.services.lead_service import soft_delete_lead_by_id
from app.services.pipeline_service import ensure_pipeline_stages, reorder_pipeline_stages
from app.services.tenant_service import get_current_tenant

router = APIRouter(tags=["leads"])
logger = logging.getLogger(__name__)


class PipelineStageCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    position: int | None = Field(default=None, ge=0)


class PipelineStageUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    position: int | None = Field(default=None, ge=0)


class PipelineStageReorderRequest(BaseModel):
    stage_ids: list[uuid.UUID] = Field(min_length=1)


def _serialize_stage(stage: PipelineStage, leads: list[PipelineLeadOut] | None = None) -> PipelineStageOut:
    return PipelineStageOut(id=stage.id, name=stage.name, position=stage.position, is_final_stage=bool(getattr(stage, "is_final_stage", False)), leads=leads or [])


def _get_stage_or_404(db: Session, tenant_id: uuid.UUID, stage_id: uuid.UUID) -> PipelineStage:
    tenant_stage_count = db.execute(
        select(func.count(PipelineStage.id)).where(PipelineStage.tenant_id == tenant_id)
    ).scalar_one()
    logger.info(
        "[PIPELINE UPDATE LOOKUP] stage_id=%s tenant_id=%s tenant_stage_count=%s model=%s",
        stage_id,
        tenant_id,
        tenant_stage_count,
        f"{PipelineStage.__module__}.{PipelineStage.__name__}",
    )
    stage = db.execute(
        select(PipelineStage).where(
            PipelineStage.id == stage_id,
            PipelineStage.tenant_id == tenant_id,
        )
    ).scalars().first()
    if not stage:
        logger.warning(
            "[PIPELINE UPDATE NOT FOUND] stage_id=%s tenant_id=%s tenant_stage_count=%s model=%s",
            stage_id,
            tenant_id,
            tenant_stage_count,
            f"{PipelineStage.__module__}.{PipelineStage.__name__}",
        )
        raise HTTPException(status_code=404, detail="Etapa do pipeline não encontrada")
    logger.info(
        "[PIPELINE UPDATE FOUND] stage_id=%s tenant_id=%s tenant_stage_count=%s model=%s loaded_stage_id=%s",
        stage_id,
        tenant_id,
        tenant_stage_count,
        f"{stage.__class__.__module__}.{stage.__class__.__name__}",
        stage.id,
    )
    return stage


def _ordered_stages(db: Session, tenant_id: uuid.UUID) -> list[PipelineStage]:
    return (
        db.execute(
            select(PipelineStage)
            .where(PipelineStage.tenant_id == tenant_id)
            .order_by(PipelineStage.position.asc(), PipelineStage.created_at.asc(), PipelineStage.id.asc())
        )
        .scalars()
        .all()
    )


@router.get("/leads", response_model=list[LeadOut])
def list_leads(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    return (
        db.execute(
            select(Lead)
            .where(Lead.tenant_id == tenant.id, Lead.status == LeadStatus.ACTIVE.value)
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
    stages = ensure_pipeline_stages(
        db, tenant.id, workspace_profile=tenant.workspace_profile, commit_created=True
    )

    leads = (
        db.execute(
            select(Lead)
            .where(Lead.tenant_id == tenant.id, Lead.status != LeadStatus.DELETED.value)
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

    return [_serialize_stage(stage, grouped.get(stage.id, [])) for stage in sorted(stages, key=lambda item: item.position)]


@router.get("/pipeline/stages", response_model=list[PipelineStageOut])
def list_pipeline_stages(
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    stages = ensure_pipeline_stages(
        db, tenant.id, workspace_profile=tenant.workspace_profile, commit_created=True
    )
    return [_serialize_stage(stage) for stage in sorted(stages, key=lambda item: item.position)]


@router.post("/pipeline", response_model=PipelineStageOut)
def create_pipeline_stage(
    payload: PipelineStageCreate,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    ensure_pipeline_stages(db, tenant.id, workspace_profile=tenant.workspace_profile)
    max_position = db.execute(
        select(func.coalesce(func.max(PipelineStage.position), -1)).where(PipelineStage.tenant_id == tenant.id)
    ).scalar_one()
    position = max_position + 1 if payload.position is None else min(payload.position, max_position + 1)

    try:
        stage = PipelineStage(tenant_id=tenant.id, name=payload.name.strip(), position=max_position + 1)
        db.add(stage)
        db.flush()
        existing_stages = [item for item in _ordered_stages(db, tenant.id) if item.id != stage.id]
        reorder_pipeline_stages(db, existing_stages, extra_stage=stage, insert_position=position)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Já existe uma etapa com este nome ou posição") from exc
    db.refresh(stage)
    return _serialize_stage(stage)


@router.put("/pipeline/{stage_id}", response_model=PipelineStageOut)
def update_pipeline_stage(
    stage_id: uuid.UUID,
    payload: PipelineStageUpdate,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    logger.info(
        "[PIPELINE UPDATE REQUEST] stage_id=%s tenant_id=%s payload=%s",
        stage_id,
        tenant.id,
        payload.model_dump(exclude_none=True),
    )
    stage = _get_stage_or_404(db, tenant.id, stage_id)
    if payload.name is not None:
        stage.name = payload.name.strip()
    try:
        if payload.position is not None and payload.position != stage.position:
            stages = [item for item in _ordered_stages(db, tenant.id) if item.id != stage.id]
            reorder_pipeline_stages(db, stages, extra_stage=stage, insert_position=payload.position)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Já existe uma etapa com este nome ou posição") from exc
    db.refresh(stage)
    return _serialize_stage(stage)


@router.patch("/pipeline/reorder", response_model=list[PipelineStageOut])
def reorder_pipeline(
    payload: PipelineStageReorderRequest,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    stages = ensure_pipeline_stages(db, tenant.id, workspace_profile=tenant.workspace_profile)
    stage_by_id = {stage.id: stage for stage in stages}
    requested_ids = payload.stage_ids
    if len(set(requested_ids)) != len(requested_ids):
        raise HTTPException(status_code=422, detail="A lista de etapas contém duplicidades")
    missing_ids = [stage_id for stage_id in requested_ids if stage_id not in stage_by_id]
    if missing_ids:
        raise HTTPException(status_code=404, detail="Uma ou mais etapas não pertencem ao tenant atual")

    ordered = [stage_by_id[stage_id] for stage_id in requested_ids]
    remaining = [stage for stage in sorted(stages, key=lambda item: item.position) if stage.id not in set(requested_ids)]
    try:
        reorder_pipeline_stages(db, ordered + remaining)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="Não foi possível reordenar as etapas") from exc
    return [_serialize_stage(stage) for stage in _ordered_stages(db, tenant.id)]


@router.delete("/pipeline/{stage_id}")
def delete_pipeline_stage(
    stage_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    stages = ensure_pipeline_stages(db, tenant.id, workspace_profile=tenant.workspace_profile)
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
    db.flush()
    reorder_pipeline_stages(db, [item for item in stages if item.id != stage.id])
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

    previous_stage_id = lead.stage_id
    lead.stage_id = target_stage.id
    lead.entered_stage_at = datetime.utcnow()
    lead.updated_at = datetime.utcnow()
    action = "LEAD_CONVERTED" if target_stage.is_final_stage else "LEAD_MOVED"
    if target_stage.is_final_stage:
        lead.status = LeadStatus.CONVERTED.value
    else:
        lead.status = LeadStatus.ACTIVE.value
    write_audit_log(
        db,
        action=action,
        tenant_id=tenant.id,
        user_id=lead.owner_id,
        entity_type="lead",
        entity_id=lead.id,
        metadata={
            "from_stage_id": str(previous_stage_id) if previous_stage_id else None,
            "to_stage_id": str(target_stage.id),
            "to_stage": target_stage.name,
            "event": "Lead concluído" if target_stage.is_final_stage else "Lead movido de etapa",
        },
    )

    db.commit()
    db.refresh(lead)
    return lead


@router.delete("/leads/{lead_id}")
def delete_lead(
    lead_id: uuid.UUID,
    tenant: Tenant = Depends(get_current_tenant),
    db: Session = Depends(get_db),
):
    result = soft_delete_lead_by_id(db, tenant_id=tenant.id, lead_id=lead_id)
    if not result:
        raise HTTPException(status_code=404, detail="Lead não encontrado")

    db.commit()
    return {"deleted": True}


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
