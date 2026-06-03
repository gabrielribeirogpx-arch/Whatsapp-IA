from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class FlowV2SnapshotView:
    version: str | int | None
    hash: str | None
    nodes_count: int
    edges_count: int
    snapshot: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "hash": self.hash,
            "nodes_count": self.nodes_count,
            "edges_count": self.edges_count,
            "snapshot": self.snapshot,
        }


class FlowV2SnapshotViewer:
    """Read-only viewer for immutable Flow Publisher V2 snapshots."""

    def view(self, snapshot: dict[str, Any]) -> FlowV2SnapshotView:
        if not isinstance(snapshot, dict):
            raise ValueError("Flow V2 snapshot must be a dict")
        nodes = snapshot.get("nodes") if isinstance(snapshot.get("nodes"), list) else []
        edges = snapshot.get("edges") if isinstance(snapshot.get("edges"), list) else []
        return FlowV2SnapshotView(
            version=snapshot.get("version") or snapshot.get("schema_version"),
            hash=snapshot.get("hash") or snapshot.get("v2_snapshot_hash"),
            nodes_count=len(nodes),
            edges_count=len(edges),
            snapshot=snapshot,
        )
