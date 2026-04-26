from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import select

from app.db.session import SessionLocal
from app.models import Flow, FlowEdge, FlowNode, FlowVersion
from app.services.flow_engine_service import validate_flow_structure


@dataclass
class FlowSnapshot:
    id: str
    tenant_id: str
    name: str
    is_active: bool
    trigger_type: str
    trigger_value: str | None
    version: int
    current_version_id: str | None
    versions_count: int
    persisted_nodes_count: int
    persisted_edges_count: int
    nodes_count: int
    edges_count: int
    raw_nodes: list[dict]
    is_valid: bool
    validation_error: str | None


def _safe_nodes(payload: list[dict] | None) -> list[dict]:
    if not payload:
        return []
    return [node if isinstance(node, dict) else {"value": node} for node in payload]


def scan_all_flows() -> list[FlowSnapshot]:
    db = SessionLocal()
    try:
        flows = db.execute(
            select(Flow).order_by(Flow.created_at.asc(), Flow.id.asc())
        ).scalars().all()

        versions = db.execute(select(FlowVersion)).scalars().all()
        version_by_id = {str(item.id): item for item in versions}
        versions_per_flow: dict[str, int] = defaultdict(int)
        for item in versions:
            versions_per_flow[str(item.flow_id)] += 1

        persisted_nodes_per_flow: dict[str, int] = defaultdict(int)
        for node_flow_id in db.execute(select(FlowNode.flow_id)).scalars().all():
            persisted_nodes_per_flow[str(node_flow_id)] += 1

        persisted_edges_per_flow: dict[str, int] = defaultdict(int)
        for edge_flow_id in db.execute(select(FlowEdge.flow_id)).scalars().all():
            persisted_edges_per_flow[str(edge_flow_id)] += 1

        snapshots: list[FlowSnapshot] = []
        for flow in flows:
            flow_id = str(flow.id)
            current_version = version_by_id.get(str(flow.current_version_id)) if flow.current_version_id else None

            raw_nodes = _safe_nodes(current_version.nodes if current_version else None)
            edges = current_version.edges if current_version and isinstance(current_version.edges, list) else []
            valid, validation_error = validate_flow_structure(
                nodes=raw_nodes if isinstance(raw_nodes, list) else [],
                edges=edges if isinstance(edges, list) else [],
            )

            if not raw_nodes:
                print(
                    json.dumps(
                        {
                            "event": "flow_without_nodes",
                            "flow_id": flow_id,
                            "current_version_id": str(flow.current_version_id) if flow.current_version_id else None,
                        },
                        ensure_ascii=False,
                    )
                )
            if not valid:
                print(
                    json.dumps(
                        {
                            "event": "flow_inconsistent",
                            "flow_id": flow_id,
                            "current_version_id": str(flow.current_version_id) if flow.current_version_id else None,
                            "detail": validation_error,
                        },
                        ensure_ascii=False,
                    )
                )

            snapshots.append(
                FlowSnapshot(
                    id=flow_id,
                    tenant_id=str(flow.tenant_id),
                    name=flow.name,
                    is_active=bool(flow.is_active),
                    trigger_type=flow.trigger_type,
                    trigger_value=flow.trigger_value,
                    version=flow.version,
                    current_version_id=str(flow.current_version_id) if flow.current_version_id else None,
                    versions_count=versions_per_flow[flow_id],
                    persisted_nodes_count=persisted_nodes_per_flow[flow_id],
                    persisted_edges_count=persisted_edges_per_flow[flow_id],
                    nodes_count=len(raw_nodes),
                    edges_count=len(edges) if isinstance(edges, list) else 0,
                    raw_nodes=raw_nodes,
                    is_valid=valid,
                    validation_error=validation_error,
                )
            )

        return snapshots
    finally:
        db.close()


def scan_all() -> list[FlowSnapshot]:
    return scan_all_flows()


def main() -> None:
    snapshots = scan_all_flows()

    print(f"TOTAL FLOWS: {len(snapshots)}")
    for item in snapshots:
        print(json.dumps(asdict(item), ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
