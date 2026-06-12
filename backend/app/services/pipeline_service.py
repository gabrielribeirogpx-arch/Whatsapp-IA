from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.pipeline_stage import PipelineStage

WORKSPACE_PROFILE_PRIVATE_SALES = "private_sales"
WORKSPACE_PROFILE_GOVERNMENT = "government"
WORKSPACE_PROFILES = {WORKSPACE_PROFILE_PRIVATE_SALES, WORKSPACE_PROFILE_GOVERNMENT}

DEFAULT_PIPELINE_STAGES_BY_PROFILE = {
    WORKSPACE_PROFILE_PRIVATE_SALES: [
        "Novo",
        "Qualificado",
        "Proposta",
        "Fechamento",
        "Ganho",
    ],
    WORKSPACE_PROFILE_GOVERNMENT: [
        "Entrada",
        "Triagem",
        "Em atendimento",
        "Aguardando cidadão",
        "Concluído",
    ],
}
DEFAULT_PIPELINE_STAGES = DEFAULT_PIPELINE_STAGES_BY_PROFILE[WORKSPACE_PROFILE_PRIVATE_SALES]
TEMP_POSITION_OFFSET = 10_000


def normalize_workspace_profile(workspace_profile: str | None) -> str:
    if workspace_profile in WORKSPACE_PROFILES:
        return workspace_profile
    return WORKSPACE_PROFILE_PRIVATE_SALES


def get_default_pipeline_stage_names(workspace_profile: str | None = None) -> list[str]:
    normalized = normalize_workspace_profile(workspace_profile)
    return DEFAULT_PIPELINE_STAGES_BY_PROFILE[normalized]


def ensure_single_final_stage(db: Session, tenant_id) -> PipelineStage | None:
    stages = (
        db.execute(
            select(PipelineStage)
            .where(PipelineStage.tenant_id == tenant_id)
            .order_by(PipelineStage.position.asc(), PipelineStage.created_at.asc(), PipelineStage.id.asc())
        )
        .scalars()
        .all()
    )
    if not stages:
        return None

    final_stages = [stage for stage in stages if bool(getattr(stage, "is_final_stage", False))]
    selected = final_stages[0] if final_stages else stages[-1]
    for stage in stages:
        stage.is_final_stage = stage.id == selected.id
    db.flush()
    return selected


def ensure_pipeline_stages(
    db: Session,
    tenant_id,
    workspace_profile: str | None = None,
    *,
    commit_created: bool = False,
) -> list[PipelineStage]:
    stages = (
        db.execute(
            select(PipelineStage)
            .where(PipelineStage.tenant_id == tenant_id)
            .order_by(PipelineStage.position.asc(), PipelineStage.created_at.asc(), PipelineStage.id.asc())
        )
        .scalars()
        .all()
    )
    if stages:
        ensure_single_final_stage(db, tenant_id)
        return stages

    stage_names = get_default_pipeline_stage_names(workspace_profile)
    created: list[PipelineStage] = []
    for index, stage_name in enumerate(stage_names):
        stage = PipelineStage(
            tenant_id=tenant_id,
            name=stage_name,
            position=index,
            is_final_stage=index == len(stage_names) - 1,
        )
        db.add(stage)
        created.append(stage)

    db.flush()
    if commit_created:
        db.commit()
        for stage in created:
            db.refresh(stage)
    return created


def get_first_pipeline_stage(
    db: Session,
    tenant_id,
    workspace_profile: str | None = None,
) -> PipelineStage | None:
    stages = ensure_pipeline_stages(db, tenant_id, workspace_profile=workspace_profile)
    stage = next(iter(sorted(stages, key=lambda item: (item.position, item.created_at, item.id))), None)
    if stage:
        print("[PIPELINE FIRST STAGE]", f"tenant_id={tenant_id}", f"stage_id={stage.id}", f"stage={stage.name}")
    return stage


def reorder_pipeline_stages(
    db: Session,
    stages: list[PipelineStage],
    *,
    extra_stage: PipelineStage | None = None,
    insert_position: int | None = None,
) -> list[PipelineStage]:
    """Renumber stages without violating tenant/position uniqueness mid-transaction."""
    ordered = list(stages)
    if extra_stage is not None:
        bounded_position = min(max(insert_position or 0, 0), len(ordered))
        ordered.insert(bounded_position, extra_stage)
    elif insert_position is not None:
        ordered = [*ordered[:insert_position], *ordered[insert_position:]]

    for index, stage in enumerate(ordered):
        stage.position = TEMP_POSITION_OFFSET + index
    db.flush()

    for index, stage in enumerate(ordered):
        stage.position = index

    final_stage = next((stage for stage in ordered if bool(getattr(stage, "is_final_stage", False))), ordered[-1] if ordered else None)
    for stage in ordered:
        stage.is_final_stage = bool(final_stage and stage.id == final_stage.id)

    db.flush()
    return ordered
