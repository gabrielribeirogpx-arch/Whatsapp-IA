from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter(tags=["flow-runtime-v2-health"])


@router.get("/flow-v2/runtime/health")
def runtime_health(db: Session = Depends(get_db)) -> dict[str, object]:
    """Runtime V2 production health probe."""

    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    return {
        "status": "ok" if db_ok else "degraded",
        "runtime": "flow_v2",
        "database": "ok" if db_ok else "unavailable",
        "idempotency": "enabled",
        "locking": "enabled",
        "dead_letter_queue": "enabled",
    }
