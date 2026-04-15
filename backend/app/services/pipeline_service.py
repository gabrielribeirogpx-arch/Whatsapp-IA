from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import PipelineStage

DEFAULT_PIPELINE_STAGES = [
    "Novo",
    "Qualificado",
    "Proposta",
    "Fechamento",
    "Ganho",
]


def ensure_pipeline_stages(db: Session, tenant_id) -> list[PipelineStage]:
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
    for index, stage_name in enumerate(DEFAULT_PIPELINE_STAGES):
        stage = PipelineStage(tenant_id=tenant_id, name=stage_name, position=index)
        db.add(stage)
        created.append(stage)

    db.flush()
    return created
