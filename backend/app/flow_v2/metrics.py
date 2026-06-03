from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.flow_v2.contracts import FlowV2EventType, FlowV2SessionStatus
from app.flow_v2.models import FlowV2Event, FlowV2Session


@dataclass(frozen=True)
class FlowV2MetricsSnapshot:
    sessions_started: int
    sessions_completed: int
    sessions_failed: int
    average_duration: float
    choice_conversion: float
    active_sessions: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "sessions_started": self.sessions_started,
            "sessions_completed": self.sessions_completed,
            "sessions_failed": self.sessions_failed,
            "average_duration": self.average_duration,
            "choice_conversion": self.choice_conversion,
            "active_sessions": self.active_sessions,
        }


class FlowV2MetricsAggregator:
    """Aggregates production metrics directly from V2 sessions and events."""

    def snapshot(self, db: Session, *, tenant_id: UUID | None = None) -> FlowV2MetricsSnapshot:
        sessions = self._load_sessions(db, tenant_id=tenant_id)
        events = self._load_events(db, tenant_id=tenant_id)

        started = sum(1 for session in sessions if getattr(session, "started_at", None) is not None)
        completed_sessions = [s for s in sessions if str(getattr(s, "status", "")) == str(FlowV2SessionStatus.COMPLETED)]
        failed = sum(1 for s in sessions if str(getattr(s, "status", "")) == str(FlowV2SessionStatus.FAILED))
        active = sum(1 for s in sessions if str(getattr(s, "status", "")) in {str(FlowV2SessionStatus.RUNNING), str(FlowV2SessionStatus.WAITING)})
        durations = [self._duration_seconds(s) for s in completed_sessions if self._duration_seconds(s) is not None]
        choices_shown = sum(1 for e in events if str(getattr(e, "event_type", "")) == str(FlowV2EventType.CHOICE_SHOWN))
        choices_selected = sum(1 for e in events if str(getattr(e, "event_type", "")) == str(FlowV2EventType.CHOICE_SELECTED))
        return FlowV2MetricsSnapshot(
            sessions_started=started,
            sessions_completed=len(completed_sessions),
            sessions_failed=failed,
            average_duration=(sum(durations) / len(durations)) if durations else 0.0,
            choice_conversion=(choices_selected / choices_shown) if choices_shown else 0.0,
            active_sessions=active,
        )

    def _load_sessions(self, db: Session, *, tenant_id: UUID | None) -> list[Any]:
        if hasattr(db, "flow_v2_sessions"):
            return list(db.flow_v2_sessions)
        stmt = select(FlowV2Session)
        if tenant_id is not None:
            stmt = stmt.where(FlowV2Session.tenant_id == tenant_id)
        return list(db.execute(stmt).scalars())

    def _load_events(self, db: Session, *, tenant_id: UUID | None) -> list[Any]:
        if hasattr(db, "flow_v2_events"):
            return list(db.flow_v2_events)
        stmt = select(FlowV2Event)
        if tenant_id is not None:
            stmt = stmt.where(FlowV2Event.tenant_id == tenant_id)
        return list(db.execute(stmt).scalars())

    @staticmethod
    def _duration_seconds(session: Any) -> float | None:
        started = getattr(session, "started_at", None)
        ended = getattr(session, "updated_at", None)
        if not isinstance(started, datetime) or not isinstance(ended, datetime):
            return None
        return max((ended - started).total_seconds(), 0.0)
