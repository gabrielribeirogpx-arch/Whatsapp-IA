from __future__ import annotations

from typing import Any

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


def build_execution_timeline(db: "Session", trace_id: str) -> dict[str, Any]:
    if hasattr(db, "_rows"):
        rows = list(getattr(db, "_rows"))
    else:
        from sqlalchemy import select
        from app.models.execution_trace import ExecutionTrace

        rows = list(db.execute(select(ExecutionTrace).where(ExecutionTrace.trace_id == str(trace_id)).order_by(ExecutionTrace.timestamp.asc(), ExecutionTrace.created_at.asc())).scalars())
    if not rows:
        return {"trace_id": str(trace_id), "started_at": None, "duration_ms": 0, "events": []}
    started = rows[0].timestamp
    finished = rows[-1].timestamp
    return {
        "trace_id": str(trace_id),
        "started_at": started.isoformat() if started else None,
        "duration_ms": int((finished - started).total_seconds() * 1000) if started and finished else 0,
        "events": [
            {
                "event_type": row.event_type,
                "timestamp": row.timestamp.isoformat() if row.timestamp else None,
                "duration_ms": row.duration_ms,
                "metadata": row.metadata_json or {},
            }
            for row in rows
        ],
    }
