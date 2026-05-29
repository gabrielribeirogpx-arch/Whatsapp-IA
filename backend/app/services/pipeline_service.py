from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import PipelineStage

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
            .order_by(PipelineStage.position.asc(), PipelineStage.created_at.asc())
        )
        .scalars()
        .all()
    )
    if stages:
        return stages

    created: list[PipelineStage] = []
    for index, stage_name in enumerate(get_default_pipeline_stage_names(workspace_profile)):
        stage = PipelineStage(tenant_id=tenant_id, name=stage_name, position=index)
        db.add(stage)
        created.append(stage)

    db.flush()
    if commit_created:
        db.commit()
        for stage in created:
            db.refresh(stage)
    return created


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
    db.flush()
    return ordered
