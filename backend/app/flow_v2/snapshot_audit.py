from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.flow_v2.snapshot import canonical_hash
from app.models.flow import FlowVersion


@dataclass(frozen=True)
class SnapshotAuditIssue:
    flow_version_id: str
    code: str
    message: str


@dataclass(frozen=True)
class SnapshotAuditReport:
    status: str
    checked_versions: int
    issues: tuple[SnapshotAuditIssue, ...]

    @property
    def passed(self) -> bool:
        return self.status == "PASSED"


class FlowV2SnapshotAuditor:
    """Audits immutable Flow V2 snapshots persisted on FlowVersion rows."""

    def audit_db(self, db: Session, *, tenant_id: UUID | None = None) -> SnapshotAuditReport:
        statement = select(FlowVersion).where(FlowVersion.snapshot.is_not(None))
        if tenant_id is not None:
            statement = statement.where(FlowVersion.tenant_id == tenant_id)
        versions = db.execute(statement).scalars().all()
        return self.audit_versions(versions)

    def audit_versions(self, versions: Iterable[Any]) -> SnapshotAuditReport:
        issues: list[SnapshotAuditIssue] = []
        checked = 0
        for version in versions:
            checked += 1
            issues.extend(self._audit_version(version))
        return SnapshotAuditReport(
            status="PASSED" if not issues else "FAILED",
            checked_versions=checked,
            issues=tuple(issues),
        )

    def _audit_version(self, version: Any) -> list[SnapshotAuditIssue]:
        version_id = str(getattr(version, "id", "<unknown>"))
        snapshot = getattr(version, "snapshot", None)
        issues: list[SnapshotAuditIssue] = []
        if not isinstance(snapshot, dict):
            return [SnapshotAuditIssue(version_id, "SNAPSHOT_MISSING", "FlowVersion snapshot must be a dictionary")]

        schema_version = snapshot.get("snapshot_schema_version") or snapshot.get("schema_version")
        if not isinstance(schema_version, int) or schema_version <= 0:
            issues.append(SnapshotAuditIssue(version_id, "SCHEMA_VERSION_INVALID", "Snapshot schema_version must be a positive integer"))

        nodes = snapshot.get("nodes")
        edges = snapshot.get("edges")
        if not isinstance(nodes, list):
            issues.append(SnapshotAuditIssue(version_id, "NODES_INVALID", "Snapshot nodes must be a list"))
            nodes = []
        if not isinstance(edges, list):
            issues.append(SnapshotAuditIssue(version_id, "EDGES_INVALID", "Snapshot edges must be a list"))
            edges = []

        expected_nodes = _optional_int(getattr(version, "nodes_count", None))
        if expected_nodes is not None and expected_nodes != len(nodes):
            issues.append(SnapshotAuditIssue(version_id, "NODE_COUNT_MISMATCH", f"Expected {expected_nodes} nodes, found {len(nodes)}"))

        expected_edges = _optional_int(getattr(version, "edges_count", None))
        if expected_edges is not None and expected_edges != len(edges):
            issues.append(SnapshotAuditIssue(version_id, "EDGE_COUNT_MISMATCH", f"Expected {expected_edges} edges, found {len(edges)}"))

        embedded_hash = snapshot.get("hash")
        stored_hash = getattr(version, "v2_snapshot_hash", None) or getattr(version, "graph_hash", None) or embedded_hash
        actual_hash = canonical_hash({key: value for key, value in snapshot.items() if key != "hash"})
        if not isinstance(stored_hash, str) or len(stored_hash) != 64:
            issues.append(SnapshotAuditIssue(version_id, "HASH_MISSING", "Snapshot hash must be persisted on the version"))
        elif stored_hash != actual_hash:
            issues.append(SnapshotAuditIssue(version_id, "HASH_MISMATCH", "Persisted snapshot hash does not match canonical snapshot hash"))
        if embedded_hash is not None and embedded_hash != actual_hash:
            issues.append(SnapshotAuditIssue(version_id, "EMBEDDED_HASH_MISMATCH", "Embedded snapshot hash does not match canonical snapshot hash"))

        return issues


def audit_snapshots(versions: Iterable[Any]) -> SnapshotAuditReport:
    return FlowV2SnapshotAuditor().audit_versions(versions)


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
