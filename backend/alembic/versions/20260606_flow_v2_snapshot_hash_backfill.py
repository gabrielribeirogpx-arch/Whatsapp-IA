"""flow v2 snapshot hash backfill

Revision ID: 20260606_v2_snapshot_hash
Revises: 20260605_flow_runtime_selector
Create Date: 2026-06-06
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "20260606_v2_snapshot_hash"
down_revision = "20260605_flow_runtime_selector"
branch_labels = None
depends_on = None

V2_SNAPSHOT_SCHEMA_VERSION = 1


def _canonical_hash(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _canonical_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _canonical_value(value[key]) for key in sorted(value.keys(), key=str)}
    if isinstance(value, list):
        return [_canonical_value(item) for item in value]
    return value


def _canonical_sort_key(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _is_start_node(node: dict[str, Any]) -> bool:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    node_type = str(node.get("type") or data.get("type") or "message").lower()
    return bool(
        node.get("isStart")
        or node.get("is_start")
        or data.get("isStart")
        or data.get("is_start")
        or node_type == "start"
        or str(node.get("id")) == "start"
    )


def _derive_start_node_id(nodes: list[dict[str, Any]], existing: Any) -> str | None:
    if existing:
        return str(existing)
    start_ids = [str(node["id"]) for node in nodes if isinstance(node, dict) and node.get("id") not in (None, "") and _is_start_node(node)]
    if len(start_ids) == 1:
        return start_ids[0]
    return None


def _snapshot_payload(*, nodes: list[dict[str, Any]], edges: list[dict[str, Any]], start_node_id: str) -> dict[str, Any]:
    canonical_nodes = sorted((_canonical_value(node) for node in nodes), key=_canonical_sort_key)
    canonical_edges = sorted((_canonical_value(edge) for edge in edges), key=_canonical_sort_key)
    return {
        "schema_version": V2_SNAPSHOT_SCHEMA_VERSION,
        "snapshot_schema_version": V2_SNAPSHOT_SCHEMA_VERSION,
        "version": "flow_v2_snapshot_v1",
        "start_node_id": start_node_id,
        "nodes": canonical_nodes,
        "edges": canonical_edges,
    }


def upgrade() -> None:
    op.execute("ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS graph_checksum VARCHAR(64)")
    op.execute("ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS v2_snapshot_hash VARCHAR(64)")
    op.execute("ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS v2_snapshot_schema_version INTEGER")
    op.execute("ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS start_node_id VARCHAR")
    op.execute("ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS start_text_preview VARCHAR(255)")
    op.execute("ALTER TABLE flow_versions ADD COLUMN IF NOT EXISTS created_from_source VARCHAR(64)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_versions_v2_snapshot_hash ON flow_versions (v2_snapshot_hash)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_flow_versions_graph_checksum ON flow_versions (graph_checksum)")

    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT fv.id, fv.snapshot, fv.nodes, fv.edges, fv.start_node_id, fv.v2_snapshot_hash
            FROM flow_versions fv
            JOIN flows f ON f.id = fv.flow_id
            WHERE f.runtime = 'v2'
              AND fv.is_published IS TRUE
              AND (
                    fv.v2_snapshot_hash IS NULL
                 OR fv.v2_snapshot_schema_version IS NULL
                 OR fv.snapshot IS NULL
                 OR NOT (fv.snapshot ? 'hash')
                 OR NOT (fv.snapshot ? 'snapshot_schema_version')
                 OR NOT (fv.snapshot ? 'start_node_id')
              )
            """
        )
    ).mappings()

    for row in rows:
        snapshot = row["snapshot"] if isinstance(row["snapshot"], dict) else {}
        nodes = snapshot.get("nodes") if isinstance(snapshot.get("nodes"), list) else row["nodes"]
        edges = snapshot.get("edges") if isinstance(snapshot.get("edges"), list) else row["edges"]
        if not isinstance(nodes, list) or not isinstance(edges, list) or not nodes:
            continue
        start_node_id = _derive_start_node_id(nodes, snapshot.get("start_node_id") or row["start_node_id"])
        if not start_node_id:
            continue
        payload = _snapshot_payload(nodes=nodes, edges=edges, start_node_id=start_node_id)
        snapshot_hash = _canonical_hash(payload)
        payload["hash"] = snapshot_hash
        bind.execute(
            sa.text(
                """
                UPDATE flow_versions
                SET snapshot = CAST(:snapshot AS JSONB),
                    nodes = CAST(:nodes AS JSONB),
                    edges = CAST(:edges AS JSONB),
                    graph_checksum = :snapshot_hash,
                    v2_snapshot_hash = :snapshot_hash,
                    v2_snapshot_schema_version = :schema_version,
                    start_node_id = :start_node_id,
                    created_from_source = COALESCE(created_from_source, 'flow_v2_hash_backfill')
                WHERE id = :id
                """
            ),
            {
                "id": row["id"],
                "snapshot": json.dumps(payload, ensure_ascii=False),
                "nodes": json.dumps(payload["nodes"], ensure_ascii=False),
                "edges": json.dumps(payload["edges"], ensure_ascii=False),
                "snapshot_hash": snapshot_hash,
                "schema_version": V2_SNAPSHOT_SCHEMA_VERSION,
                "start_node_id": start_node_id,
            },
        )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_flow_versions_v2_snapshot_hash")
    op.execute("DROP INDEX IF EXISTS ix_flow_versions_graph_checksum")
    # Keep columns/data on downgrade: Runtime V2 snapshots may depend on them after backfill.
