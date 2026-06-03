from __future__ import annotations

import traceback
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from app.flow_v2.models import FlowV2DeadLetter


@dataclass(frozen=True)
class DeadLetterResult:
    session_id: UUID | None
    error: str
    stacktrace: str


class FlowV2DeadLetterQueue:
    """Stores failed Runtime V2 events for inspection and replay."""

    def record(
        self,
        db: Session,
        *,
        tenant_id: UUID,
        session_id: UUID | None,
        flow_version_id: UUID | None,
        event: dict[str, Any],
        error: BaseException,
    ) -> DeadLetterResult:
        stack = "".join(traceback.format_exception(type(error), error, error.__traceback__))
        message = str(error)
        if hasattr(db, "add"):
            db.add(
                FlowV2DeadLetter(
                    tenant_id=tenant_id,
                    session_id=session_id,
                    flow_version_id=flow_version_id,
                    event=event,
                    error=message,
                    stacktrace=stack,
                )
            )
            if hasattr(db, "flush"):
                db.flush()
        return DeadLetterResult(session_id=session_id, error=message, stacktrace=stack)
