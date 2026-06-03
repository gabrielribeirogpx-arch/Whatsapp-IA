from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.flow_v2.metrics import FlowV2MetricsAggregator

router = APIRouter(tags=["flow-runtime-v2-metrics"])


@router.get("/flow-v2/runtime/metrics")
def runtime_metrics(tenant_id: UUID | None = Query(default=None), db: Session = Depends(get_db)) -> dict[str, object]:
    """Aggregated Runtime V2 production metrics."""

    return FlowV2MetricsAggregator().snapshot(db, tenant_id=tenant_id).as_dict()
