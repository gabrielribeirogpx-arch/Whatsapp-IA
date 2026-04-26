import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = Path(__file__).resolve().parents[1]

if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.session import SessionLocal
from app.models.flow import Flow, FlowNode, FlowEdge, FlowVersion


def scan_all():
    db = SessionLocal()
    try:
        flows = db.query(Flow).all()
        items = []

        for flow in flows:
            active_version = next((version for version in flow.versions if version.is_active), None)
            selected_version = active_version
            if selected_version is None and flow.current_version_id:
                selected_version = next(
                    (version for version in flow.versions if version.id == flow.current_version_id),
                    None,
                )

            version_nodes = selected_version.nodes if selected_version and selected_version.nodes else None
            version_edges = selected_version.edges if selected_version and selected_version.edges else None

            nodes_count = len(version_nodes) if version_nodes is not None else db.query(FlowNode).filter(FlowNode.flow_id == flow.id).count()
            edges_count = len(version_edges) if version_edges is not None else db.query(FlowEdge).filter(FlowEdge.flow_id == flow.id).count()
            raw_nodes = version_nodes if version_nodes is not None else [
                {
                    "id": str(node.id),
                    "type": node.type,
                    "content": node.content,
                    "metadata": node.metadata_json,
                }
                for node in db.query(FlowNode).filter(FlowNode.flow_id == flow.id).all()
            ]

            items.append(
                {
                    "id": str(flow.id),
                    "name": flow.name,
                    "is_active": flow.is_active,
                    "nodes_count": nodes_count,
                    "edges_count": edges_count,
                    "raw_nodes": raw_nodes,
                }
            )

        return {"total_flows": len(items), "flows": items}
    finally:
        db.close()
