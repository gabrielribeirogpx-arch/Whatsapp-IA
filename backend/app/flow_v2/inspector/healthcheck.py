from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import exists, not_, select

from app.flow_v2.models import FlowV2Event, FlowV2ScheduledJob, FlowV2Session
from app.flow_v2.snapshot import canonical_hash
from app.models.flow import FlowVersion


@dataclass(frozen=True)
class HealthcheckReport:
    orphan_session_ids: tuple[Any, ...] = field(default_factory=tuple)
    invalid_snapshot_version_ids: tuple[Any, ...] = field(default_factory=tuple)
    inconsistent_hash_version_ids: tuple[Any, ...] = field(default_factory=tuple)
    expired_job_ids: tuple[Any, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return not (
            self.orphan_session_ids
            or self.invalid_snapshot_version_ids
            or self.inconsistent_hash_version_ids
            or self.expired_job_ids
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "orphan_session_ids": [str(value) for value in self.orphan_session_ids],
            "invalid_snapshot_version_ids": [str(value) for value in self.invalid_snapshot_version_ids],
            "inconsistent_hash_version_ids": [str(value) for value in self.inconsistent_hash_version_ids],
            "expired_job_ids": [str(value) for value in self.expired_job_ids],
        }


class FlowV2Healthcheck:
    """Validates Runtime V2 consistency without mutating V1 or V2 state."""

    def check(
        self,
        db,
        *,
        tenant_id: UUID,
        now: datetime | None = None,
        expired_job_grace: timedelta = timedelta(hours=1),
    ) -> HealthcheckReport:
        now = (now or datetime.now(UTC)).replace(tzinfo=None)
        expired_before = now - expired_job_grace

        orphan_sessions = list(
            db.execute(
                select(FlowV2Session).where(
                    FlowV2Session.tenant_id == tenant_id,
                    not_(exists().where(FlowV2Event.session_id == FlowV2Session.id)),
                )
            ).scalars()
        )
        versions = list(
            db.execute(
                select(FlowVersion).where(FlowVersion.tenant_id == tenant_id, FlowVersion.is_published.is_(True))
            ).scalars()
        )
        expired_jobs = list(
            db.execute(
                select(FlowV2ScheduledJob).where(
                    FlowV2ScheduledJob.tenant_id == tenant_id,
                    FlowV2ScheduledJob.run_at < expired_before,
                )
            ).scalars()
        )
        return self.check_collections(sessions=orphan_sessions, events=[], versions=versions, jobs=expired_jobs, only_orphan_sessions=True)

    def check_collections(
        self,
        *,
        sessions: list[Any] | tuple[Any, ...],
        events: list[Any] | tuple[Any, ...],
        versions: list[Any] | tuple[Any, ...],
        jobs: list[Any] | tuple[Any, ...],
        now: datetime | None = None,
        expired_job_grace: timedelta = timedelta(hours=1),
        only_orphan_sessions: bool = False,
    ) -> HealthcheckReport:
        now = (now or datetime.now(UTC)).replace(tzinfo=None)
        event_session_ids = {self._get(event, "session_id") for event in events}
        orphan_sessions = tuple(
            self._get(session, "id")
            for session in sessions
            if only_orphan_sessions or self._get(session, "id") not in event_session_ids
        )

        invalid_versions: list[Any] = []
        inconsistent_versions: list[Any] = []
        for version in versions:
            version_id = self._get(version, "id")
            snapshot = self._get(version, "snapshot")
            if not self._valid_snapshot(snapshot):
                invalid_versions.append(version_id)
                continue
            expected_hash = self._get(version, "v2_snapshot_hash") or snapshot.get("hash")
            actual_hash = canonical_hash({key: value for key, value in snapshot.items() if key != "hash"})
            if expected_hash != actual_hash:
                inconsistent_versions.append(version_id)

        expired_before = now - expired_job_grace
        expired_jobs = tuple(
            self._get(job, "id")
            for job in jobs
            if self._get(job, "run_at") is not None and self._get(job, "run_at") < expired_before
        )
        return HealthcheckReport(
            orphan_session_ids=tuple(value for value in orphan_sessions if value is not None),
            invalid_snapshot_version_ids=tuple(value for value in invalid_versions if value is not None),
            inconsistent_hash_version_ids=tuple(value for value in inconsistent_versions if value is not None),
            expired_job_ids=tuple(value for value in expired_jobs if value is not None),
        )

    @staticmethod
    def _valid_snapshot(snapshot: Any) -> bool:
        return (
            isinstance(snapshot, dict)
            and isinstance(snapshot.get("nodes"), list)
            and isinstance(snapshot.get("edges"), list)
            and bool(snapshot.get("start_node_id"))
        )

    @staticmethod
    def _get(item: Any, key: str, default: Any = None) -> Any:
        if isinstance(item, dict):
            return item.get(key, default)
        return getattr(item, key, default)
