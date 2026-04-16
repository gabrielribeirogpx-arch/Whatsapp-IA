import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import desc, func, select
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

router = APIRouter(prefix="/api", tags=["leads"])


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
    print("➡️ GET /api/pipeline START")
    tenant_id = getattr(tenant, "id", None)
    print("TENANT DEBUG:", tenant_id)
    if tenant_id is None:
        print("🚨 TENANT NÃO IDENTIFICADO")
    try:
        stages = ensure_pipeline_stages(db, tenant.id)

        try:
            leads = db.execute(
                select(
                    Lead.id,
                    Lead.name,
                    Lead.phone,
                    Lead.last_message,
                    Lead.temperature,
                    Lead.score,
                    Lead.last_interaction,
                    Lead.stage,
                )
                .where(Lead.tenant_id == tenant.id)
                .order_by(desc(Lead.score), desc(Lead.last_interaction), desc(Lead.created_at))
            ).all()
        except Exception as e:
            print("💣 DB ERROR:", str(e))
            raise

        grouped: dict[uuid.UUID, list[PipelineLeadOut]] = {stage.id: [] for stage in stages}
        fallback_stage_id = stages[0].id if stages else None

        stage_name_to_id = {stage.name.casefold(): stage.id for stage in stages}
        stage_aliases = {
            "lead": "novo",
            "qualificado": "qualificado",
            "proposta": "proposta",
            "fechado": "fechamento",
            "perdido": "ganho",
        }

        for lead in leads:
            lead_stage = (lead.stage or "").casefold()
            normalized_stage = stage_aliases.get(lead_stage, lead_stage)
            target_stage_id = stage_name_to_id.get(normalized_stage) or fallback_stage_id
            if not target_stage_id:
                continue
            if target_stage_id not in grouped:
                grouped[target_stage_id] = []
            grouped[target_stage_id].append(
                PipelineLeadOut(
                    id=lead.id,
                    name=lead.name,
                    phone=lead.phone,
                    last_message=lead.last_message,
                    temperature=lead.temperature,
                    score=lead.score,
                    stage_id=target_stage_id,
                    last_interaction=lead.last_interaction,
                )
            )

        response = [
            PipelineStageOut(
                id=stage.id,
                name=stage.name,
                position=stage.position,
                leads=grouped.get(stage.id, []),
            )
            for stage in sorted(stages, key=lambda item: item.position)
        ]
        print("✅ GET /api/pipeline OK")
        return response
    except Exception as e:
        print("❌ GET /api/pipeline ERROR:", str(e))
        raise HTTPException(status_code=500, detail=str(e)) from e


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
