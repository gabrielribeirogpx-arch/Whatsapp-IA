from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select

from app.models.flow import FlowVersion


@dataclass(frozen=True)
class MessageChange:
    node_id: str
    before: str | None
    after: str | None

    def as_dict(self) -> dict[str, Any]:
        return {"node_id": self.node_id, "before": self.before, "after": self.after}


@dataclass(frozen=True)
class SnapshotDiffResult:
    nodes_added: tuple[str, ...]
    nodes_removed: tuple[str, ...]
    edges_added: tuple[str, ...]
    edges_removed: tuple[str, ...]
    messages_changed: tuple[MessageChange, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "nodes_added": list(self.nodes_added),
            "nodes_removed": list(self.nodes_removed),
            "edges_added": list(self.edges_added),
            "edges_removed": list(self.edges_removed),
            "messages_changed": [change.as_dict() for change in self.messages_changed],
        }


class FlowV2SnapshotDiff:
    """Compares two immutable published Flow V2 snapshots."""

    def diff_published_versions(
        self,
        db,
        *,
        tenant_id: UUID,
        before_flow_version_id: UUID,
        after_flow_version_id: UUID,
    ) -> SnapshotDiffResult:
        versions = list(
            db.execute(
                select(FlowVersion).where(
                    FlowVersion.tenant_id == tenant_id,
                    FlowVersion.id.in_([before_flow_version_id, after_flow_version_id]),
                    FlowVersion.is_published.is_(True),
                )
            ).scalars()
        )
        by_id = {version.id: version for version in versions}
        before = by_id.get(before_flow_version_id)
        after = by_id.get(after_flow_version_id)
        if before is None or after is None:
            raise ValueError("Both Flow V2 versions must be published and belong to tenant")
        return self.diff_snapshots(before.snapshot, after.snapshot)

    def diff_snapshots(self, before: dict[str, Any], after: dict[str, Any]) -> SnapshotDiffResult:
        before_nodes = self._by_id(before.get("nodes"))
        after_nodes = self._by_id(after.get("nodes"))
        before_edges = self._edge_keys(before.get("edges"))
        after_edges = self._edge_keys(after.get("edges"))

        shared_nodes = sorted(set(before_nodes) & set(after_nodes))
        changes = tuple(
            MessageChange(node_id=node_id, before=self._message(before_nodes[node_id]), after=self._message(after_nodes[node_id]))
            for node_id in shared_nodes
            if self._message(before_nodes[node_id]) != self._message(after_nodes[node_id])
        )
        return SnapshotDiffResult(
            nodes_added=tuple(sorted(set(after_nodes) - set(before_nodes))),
            nodes_removed=tuple(sorted(set(before_nodes) - set(after_nodes))),
            edges_added=tuple(sorted(set(after_edges) - set(before_edges))),
            edges_removed=tuple(sorted(set(before_edges) - set(after_edges))),
            messages_changed=changes,
        )

    @staticmethod
    def _by_id(items: Any) -> dict[str, dict[str, Any]]:
        if not isinstance(items, list):
            return {}
        return {str(item["id"]): item for item in items if isinstance(item, dict) and item.get("id") is not None}

    @classmethod
    def _edge_keys(cls, items: Any) -> set[str]:
        if not isinstance(items, list):
            return set()
        keys: set[str] = set()
        for edge in items:
            if not isinstance(edge, dict):
                continue
            keys.add(str(edge.get("id") or cls._stable_edge_key(edge)))
        return keys

    @staticmethod
    def _stable_edge_key(edge: dict[str, Any]) -> str:
        comparable = {key: edge.get(key) for key in ("source", "sourceHandle", "target", "targetHandle") if edge.get(key) is not None}
        return json.dumps(comparable, sort_keys=True, separators=(",", ":"), ensure_ascii=False)

    @staticmethod
    def _message(node: dict[str, Any]) -> str | None:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        value = node.get("content") or node.get("text") or data.get("content") or data.get("text") or data.get("message")
        return None if value is None else str(value)
