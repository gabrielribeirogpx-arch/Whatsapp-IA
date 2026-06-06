from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.flow_v2.publisher import FlowV2Publisher, FlowV2SnapshotIntegrityError
from app.models.flow import Flow, FlowVersion


@dataclass(frozen=True)
class FlowV2PublishServiceResult:
    flow: Flow
    version: FlowVersion
    snapshot: dict[str, Any]
    active_version_id: UUID


class FlowV2PublishService:
    """Atomic Draft -> Validate -> Publisher -> FlowVersion -> active version publication."""

    def __init__(self, *, publisher: FlowV2Publisher | None = None) -> None:
        self.publisher = publisher or FlowV2Publisher()

    def publish_draft(self, db: Session, *, tenant_id: UUID, flow_id: UUID) -> FlowV2PublishServiceResult:
        transaction = nullcontext() if getattr(db, "in_transaction", lambda: False)() else db.begin()
        with transaction:
            flow = db.execute(select(Flow).where(Flow.id == flow_id, Flow.tenant_id == tenant_id)).scalar_one()
            nodes = self._draft_nodes(flow)
            edges = self._draft_edges(flow)
            published = self.publisher.publish(nodes=nodes, edges=edges)
            next_version = self._next_version(db, flow_id=flow.id)
            db.execute(update(FlowVersion).where(FlowVersion.flow_id == flow.id).values(is_active=False))
            version = FlowVersion(
                flow_id=flow.id,
                tenant_id=tenant_id,
                version=next_version,
                snapshot=published.snapshot,
                nodes=published.snapshot["nodes"],
                edges=published.snapshot["edges"],
                nodes_count=len(published.snapshot["nodes"]),
                edges_count=len(published.snapshot["edges"]),
                graph_hash=published.v2_snapshot_hash,
                graph_checksum=published.v2_snapshot_hash,
                v2_snapshot_hash=published.v2_snapshot_hash,
                v2_snapshot_schema_version=published.snapshot["snapshot_schema_version"],
                start_node_id=published.snapshot["start_node_id"],
                created_from_source="flow_v2_publish_service",
                is_active=True,
                is_published=True,
            )
            db.add(version)
            db.flush()
            self._assert_snapshot_persisted_unchanged(db, version=version, generated_snapshot=published.snapshot)
            flow.current_version_id = version.id
            flow.published_version_id = version.id
            if hasattr(flow, "active_version_id"):
                flow.active_version_id = version.id
            flow.status = "published"
            db.add(flow)
            db.flush()
            return FlowV2PublishServiceResult(flow=flow, version=version, snapshot=published.snapshot, active_version_id=version.id)

    @staticmethod
    def _assert_snapshot_persisted_unchanged(db: Session, *, version: FlowVersion, generated_snapshot: dict[str, Any]) -> None:
        db.flush()
        if not hasattr(db, "expire"):
            return
        if getattr(version, "id", None) is None:
            raise FlowV2SnapshotIntegrityError("FLOW_V2_SNAPSHOT_COMPARE_MISSING_VERSION_ID")
        db.expire(version, ["snapshot"])
        saved_snapshot = db.execute(
            select(FlowVersion.snapshot).where(FlowVersion.id == version.id)
        ).scalar_one_or_none()
        if saved_snapshot != generated_snapshot:
            raise FlowV2SnapshotIntegrityError(f"FLOW_V2_SNAPSHOT_DIVERGENCE:{version.id}")

    @staticmethod
    def _draft_nodes(flow: Flow) -> list[dict[str, Any]]:
        return list(flow.nodes_json or flow.nodes or [])

    @staticmethod
    def _draft_edges(flow: Flow) -> list[dict[str, Any]]:
        return list(flow.edges_json or flow.edges or [])

    @staticmethod
    def _next_version(db: Session, *, flow_id: UUID) -> int:
        current = db.execute(select(func.max(FlowVersion.version)).where(FlowVersion.flow_id == flow_id)).scalar_one_or_none()
        return int(current or 0) + 1
