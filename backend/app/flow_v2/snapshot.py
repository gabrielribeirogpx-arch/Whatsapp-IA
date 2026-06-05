from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.flow import FlowVersion


class FlowV2SnapshotError(RuntimeError):
    pass


@dataclass(frozen=True)
class FlowV2Snapshot:
    flow_version_id: UUID
    tenant_id: UUID
    hash: str
    nodes: tuple[dict[str, Any], ...]
    edges: tuple[dict[str, Any], ...]
    start_node_id: str
    snapshot_schema_version: int = 1

    @property
    def node_by_id(self) -> dict[str, dict[str, Any]]:
        return {str(node["id"]): node for node in self.nodes}


def canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class FlowV2SnapshotRepository:
    """Loads immutable runtime snapshots exclusively from flow_versions."""

    def load(self, db: Session, *, tenant_id: UUID, flow_version_id: UUID) -> FlowV2Snapshot:
        version = db.execute(
            select(FlowVersion).where(
                FlowVersion.id == flow_version_id,
                FlowVersion.tenant_id == tenant_id,
                FlowVersion.is_published.is_(True),
            )
        ).scalar_one_or_none()
        if version is None:
            raise FlowV2SnapshotError("Published flow version not found for Runtime V2")

        snapshot = version.snapshot
        if not isinstance(snapshot, dict):
            raise FlowV2SnapshotError("Runtime V2 requires flow_versions.snapshot")

        expected_hash = getattr(version, "v2_snapshot_hash", None)
        if not expected_hash:
            raise FlowV2SnapshotError("Runtime V2 requires an immutable snapshot hash")

        snapshot = migrate_snapshot(snapshot)
        stored_schema_version = getattr(version, "v2_snapshot_schema_version", None)
        snapshot_schema_version = int(snapshot.get("snapshot_schema_version") or snapshot.get("schema_version") or 1)
        if stored_schema_version is not None and int(stored_schema_version) != snapshot_schema_version:
            raise FlowV2SnapshotError("Flow version snapshot schema version mismatch")

        embedded_hash = snapshot.get("hash")
        if embedded_hash and embedded_hash != expected_hash:
            raise FlowV2SnapshotError("Flow version embedded snapshot hash mismatch")
        actual_hash = canonical_hash({k: v for k, v in snapshot.items() if k != "hash"})
        if expected_hash != actual_hash:
            raise FlowV2SnapshotError("Flow version snapshot hash mismatch")

        nodes = snapshot.get("nodes")
        edges = snapshot.get("edges")
        if not isinstance(nodes, list) or not isinstance(edges, list):
            raise FlowV2SnapshotError("Runtime V2 snapshot must contain nodes and edges arrays")

        start_node_id = snapshot.get("start_node_id")
        if not start_node_id:
            raise FlowV2SnapshotError("Runtime V2 snapshot must declare start_node_id")

        return FlowV2Snapshot(
            flow_version_id=version.id,
            tenant_id=tenant_id,
            hash=expected_hash,
            nodes=tuple(dict(node) for node in nodes),
            edges=tuple(dict(edge) for edge in edges),
            start_node_id=str(start_node_id),
            snapshot_schema_version=snapshot_schema_version,
        )


def migrate_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Return a runtime snapshot in the current schema.

    Sprint 6 keeps migrations intentionally small: legacy V2 snapshots with only
    schema_version are read as snapshot_schema_version=1. Future migrations can
    branch on this function without mutating the immutable database row.
    """

    schema_version = int(snapshot.get("snapshot_schema_version") or snapshot.get("schema_version") or 1)
    if schema_version == 1:
        return {**snapshot, "snapshot_schema_version": 1}
    raise FlowV2SnapshotError(f"Unsupported Runtime V2 snapshot_schema_version={schema_version}")
