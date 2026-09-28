#!/usr/bin/env python3
"""One-shot, read-only-by-rollback diagnosis of a real template promotion.

Run from ``backend``.  Output is deliberately metadata-only: arbitrary strings
are represented by their type, length and SHA-256 prefix.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import uuid
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select

from app.core.database import SessionLocal
from app.flow_v2.publish_service import FlowV2PublishService
from app.models import Flow, FlowVersion, MarketplaceTemplateVersion
from app.services.assistant_configuration_service import CAPABILITY
from app.services.official_marketplace_template_service import (
    SAFE_STRUCTURAL_VALUES,
    _assistant_contract,
    publication_boundary_edges,
    remap_graph,
    sanitize_snapshot,
    structural_diff,
)

IGNORED = {"created_at", "updated_at", "published_at", "timestamp"}
MISSING = object()


def digest(value: Any, *, structural: bool = False) -> dict[str, Any]:
    """Return a value description that cannot disclose application data."""
    if value is MISSING:
        return {"type": "missing", "length": 0, "short_hash": None}
    kind = type(value).__name__
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    result = {"type": kind, "length": len(value) if isinstance(value, (str, list, dict)) else len(encoded),
              "short_hash": hashlib.sha256(encoded.encode()).hexdigest()[:12]}
    if structural and isinstance(value, str) and value in SAFE_STRUCTURAL_VALUES:
        result["value"] = value
    return result


def node_key(node: dict) -> str | None:
    data = node.get("data")
    return data.get("template_node_key") if isinstance(data, dict) and isinstance(data.get("template_node_key"), str) else None


def counts(nodes: list[dict]) -> dict[str, int]:
    return dict(sorted(Counter(str(node.get("type") or "") for node in nodes if isinstance(node, dict)).items()))


def flatten_differences(left: Any, right: Any, path: str = "") -> list[tuple[str, Any, Any]]:
    if isinstance(left, dict) and isinstance(right, dict):
        result = []
        for key in sorted((set(left) | set(right)) - IGNORED):
            child = f"{path}.{key}" if path else key
            if key not in left:
                result.append((child, MISSING, right[key]))
            elif key not in right:
                result.append((child, left[key], MISSING))
            else:
                result.extend(flatten_differences(left[key], right[key], child))
        return result
    if isinstance(left, list) and isinstance(right, list):
        result = []
        if len(left) != len(right):
            result.append((path, left, right))
        for index, (a, b) in enumerate(zip(left, right)):
            result.extend(flatten_differences(a, b, f"{path}[{index}]"))
        return result
    return [] if left == right else [(path, left, right)]


def graph_context(node_id: str, nodes: list[dict], edges: list[dict]) -> dict[str, Any]:
    by_id = {str(node.get("id")): node for node in nodes if isinstance(node, dict)}
    incoming = [edge for edge in edges if isinstance(edge, dict) and str(edge.get("target")) == node_id]
    outgoing = [edge for edge in edges if isinstance(edge, dict) and str(edge.get("source")) == node_id]
    neighbor_types = sorted(
        [str(by_id.get(str(edge.get("source")), {}).get("type") or "") for edge in incoming]
        + [str(by_id.get(str(edge.get("target")), {}).get("type") or "") for edge in outgoing]
    )
    handles = []
    for edge in incoming + outgoing:
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        for field, value in (("sourceHandle", edge.get("sourceHandle")), ("targetHandle", edge.get("targetHandle")),
                             ("data.sourceHandle", data.get("sourceHandle")), ("data.targetHandle", data.get("targetHandle")),
                             ("condition", edge.get("condition")), ("data.condition", data.get("condition"))):
            if value is not None:
                handles.append({"path": field, **digest(value, structural=True)})
    return {"in_degree": len(incoming), "out_degree": len(outgoing), "neighbor_types": neighbor_types,
            "structural_handles": handles}


def infer_assistant_mapping(db, flow: Flow, nodes: list[dict]):
    """Recover the last successful commercial mapping; failed requests are never stored."""
    prior = db.scalars(select(MarketplaceTemplateVersion).where(
        MarketplaceTemplateVersion.source_flow_id == flow.id,
    ).order_by(MarketplaceTemplateVersion.created_at.desc())).first()
    if prior is None or CAPABILITY not in (prior.manifest or {}).get("capabilities", []):
        return None, None
    prior_by_key = {node_key(node): node for node in (prior.nodes_snapshot or []) if node_key(node)}
    current_ids = {str(node.get("id")) for node in nodes}

    def ident(key):
        value = str(prior_by_key[key]["id"])
        if value not in current_ids:
            raise RuntimeError("stored assistant mapping no longer identifies the current FlowVersion")
        return uuid.UUID(value)

    targets = (prior.manifest or {}).get("assistant_materialization", {}).get("targets", [])
    clinic_target = next((item for item in targets if item.get("parameter") == "clinic_name"), {})
    mapping = SimpleNamespace(
        clinic_name_node_id=ident("assistant.clinic_name"),
        clinic_name_field=clinic_target.get("field", "data.text"),
        services_node_id=ident("assistant.services"),
        calendar_node_ids=[ident(key) for key in sorted(prior_by_key) if key.startswith("assistant.calendar.")],
        handoff_node_ids=[ident(key) for key in sorted(prior_by_key) if key.startswith("assistant.handoff.")],
    )
    return mapping, prior


def candidate_for(db, flow: Flow, source: FlowVersion) -> tuple[dict, list[dict], list[dict], str]:
    snapshot = copy.deepcopy(source.snapshot or {})
    nodes = sanitize_snapshot(snapshot.get("nodes", source.nodes or []))
    edges = sanitize_snapshot(snapshot.get("edges", source.edges or []))
    manifest = sanitize_snapshot({key: value for key, value in snapshot.items() if key not in {"nodes", "edges"}})
    manifest.update({"runtime": flow.runtime, "start_node_id": snapshot.get("start_node_id") or source.start_node_id})
    mapping, prior = infer_assistant_mapping(db, flow, nodes)
    provenance = "plain flow candidate"
    if mapping is not None:
        nodes, contract = _assistant_contract(nodes, mapping)
        capabilities = manifest.get("capabilities", [])
        manifest["capabilities"] = list(dict.fromkeys([*(capabilities if isinstance(capabilities, list) else []), CAPABILITY]))
        manifest["assistant_materialization"] = contract
        provenance = f"assistant mapping recovered from prior version {prior.version}"
    return manifest, nodes, edges, provenance


def first_concrete_difference(expected_nodes, expected_edges, actual_nodes, actual_edges, expected_start, actual_start):
    actual_by_id = {str(node.get("id")): node for node in actual_nodes if isinstance(node, dict)}
    for expected in sorted((node for node in expected_nodes if isinstance(node, dict)), key=lambda item: str(item.get("id"))):
        node_id = str(expected.get("id"))
        actual = actual_by_id.get(node_id)
        if actual is None:
            return "node_missing", expected, expected, {}, [("node", expected, MISSING)]
        changes = flatten_differences(expected, actual)
        if changes:
            return "node_attribute", expected, expected, actual, changes
    expected_edge_by_id = {str(edge.get("id")): edge for edge in expected_edges if isinstance(edge, dict)}
    actual_edge_by_id = {str(edge.get("id")): edge for edge in actual_edges if isinstance(edge, dict)}
    for edge_id in sorted(set(expected_edge_by_id) | set(actual_edge_by_id)):
        expected, actual = expected_edge_by_id.get(edge_id, {}), actual_edge_by_id.get(edge_id, {})
        changes = flatten_differences(expected, actual)
        if changes:
            endpoint = str(expected.get("source") or actual.get("source") or "")
            node = next((item for item in expected_nodes if str(item.get("id")) == endpoint), {})
            return "edge_relation", node, expected, actual, changes
    if str(expected_start) != str(actual_start):
        node = next((item for item in expected_nodes if str(item.get("id")) == str(expected_start)), {})
        return "start_node", node, {"start_node_id": expected_start}, {"start_node_id": actual_start}, [
            ("start_node_id", expected_start, actual_start)]
    return "unresolved", {}, {}, {}, []


def checkpoint_value(nodes, edges, culprit_id, edge_id=None):
    if edge_id:
        return next((edge for edge in edges if str(edge.get("id")) == edge_id), MISSING)
    return next((node for node in nodes if str(node.get("id")) == culprit_id), MISSING)


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnose one real Marketplace certification without retaining writes")
    parser.add_argument("--flow-id", required=True, type=uuid.UUID)
    args = parser.parse_args()
    db = SessionLocal()
    temporary_flow_id = temporary_version_id = None
    remaining_flows = remaining_versions = -1
    try:
        flow = db.scalar(select(Flow).where(Flow.id == args.flow_id, Flow.is_deleted.is_(False)))
        if flow is None or flow.current_version_id is None:
            raise RuntimeError("flow/current FlowVersion not found")
        source = db.scalar(select(FlowVersion).where(FlowVersion.id == flow.current_version_id,
                                                     FlowVersion.flow_id == flow.id,
                                                     FlowVersion.tenant_id == flow.tenant_id))
        if source is None:
            raise RuntimeError("current FlowVersion not found for Flow tenant")
        manifest, candidate_nodes, candidate_edges, provenance = candidate_for(db, flow, source)
        remapped_nodes, remapped_edges, mapping = remap_graph(candidate_nodes, candidate_edges)
        expected_start = mapping.get(str(manifest.get("start_node_id")))
        before_nodes, before_edges = copy.deepcopy(remapped_nodes), copy.deepcopy(remapped_edges)

        savepoint = db.begin_nested()
        try:
            temporary = Flow(id=uuid.uuid4(), tenant_id=flow.tenant_id,
                             name=f"local-certification-diagnostic-{uuid.uuid4().hex}", runtime="v2", status="draft",
                             nodes=copy.deepcopy(remapped_nodes), edges=copy.deepcopy(remapped_edges),
                             nodes_json=copy.deepcopy(remapped_nodes), edges_json=copy.deepcopy(remapped_edges))
            temporary_flow_id = temporary.id
            db.add(temporary)
            db.flush()
            published = FlowV2PublishService().publish_draft(db, tenant_id=flow.tenant_id, flow_id=temporary.id)
            temporary_version_id = published.version.id
            snapshot = copy.deepcopy(published.snapshot)
        finally:
            if savepoint.is_active:
                savepoint.rollback()

        expected_edges = publication_boundary_edges(remapped_nodes, remapped_edges)
        actual_nodes, actual_edges = snapshot["nodes"], snapshot["edges"]
        report = structural_diff(remapped_nodes, expected_edges, actual_nodes, actual_edges,
                                 expected_start, snapshot.get("start_node_id"))
        kind, culprit_node, expected_item, actual_item, changes = first_concrete_difference(
            remapped_nodes, expected_edges, actual_nodes, actual_edges, expected_start, snapshot.get("start_node_id"))
        culprit_id = str(culprit_node.get("id") or "")
        edge_id = str(expected_item.get("id")) if kind == "edge_relation" else None
        original_id = next((old for old, new in mapping.items() if new == culprit_id), None)
        source_nodes = copy.deepcopy((source.snapshot or {}).get("nodes", source.nodes or []))
        source_edges = copy.deepcopy((source.snapshot or {}).get("edges", source.edges or []))
        culprit_type = str(culprit_node.get("type") or "")
        context = graph_context(culprit_id, remapped_nodes, expected_edges) if culprit_id else {
            "in_degree": None, "out_degree": None, "neighbor_types": [], "structural_handles": []}

        checkpoints = [
            ("A. FlowVersion source", checkpoint_value(source_nodes, source_edges, original_id or "", edge_id)),
            ("B. candidate final", checkpoint_value(candidate_nodes, candidate_edges, original_id or "", edge_id)),
            ("C. after remap_graph", checkpoint_value(remapped_nodes, remapped_edges, culprit_id, edge_id)),
            ("D. before publisher", checkpoint_value(before_nodes, before_edges, culprit_id, edge_id)),
            ("E. after publisher", checkpoint_value(actual_nodes, actual_edges, culprit_id, edge_id)),
            ("F. expected after publication boundary", checkpoint_value(remapped_nodes, expected_edges, culprit_id, edge_id)),
            ("G. actual used by structural_diff", checkpoint_value(actual_nodes, actual_edges, culprit_id, edge_id)),
        ]
        path = changes[0][0] if changes else "graph"
        first_checkpoint = "UNPROVEN"
        if changes:
            def at(value, dotted):
                current = value
                for part in dotted.replace("[", ".").replace("]", "").split("."):
                    if not part:
                        continue
                    if isinstance(current, dict): current = current.get(part, MISSING)
                    elif isinstance(current, list) and part.isdigit() and int(part) < len(current): current = current[int(part)]
                    else: return MISSING
                return current
            expected_value = at(expected_item, path)
            for label, value in checkpoints:
                if label.startswith(("E.", "G.")) and at(value, path) != expected_value:
                    first_checkpoint = label
                    break
        classification = "PUBLISHER" if first_checkpoint.startswith("E.") else (
            "STRUCTURAL_COMPARATOR" if not report["equivalent"] and not changes else "PUBLICATION_BOUNDARY")

        print("CERTIFICATION REAL CASE\n")
        print(f"Flow:\n{args.flow_id}\n")
        print(f"candidate reconstruction: {provenance}\n")
        print("COUNTS")
        print(f"expected nodes: {len(remapped_nodes)}")
        print(f"actual nodes: {len(actual_nodes)}")
        print(f"expected edges: {len(expected_edges)}")
        print(f"actual edges: {len(actual_edges)}")
        print(f"expected node types: {json.dumps(counts(remapped_nodes), sort_keys=True)}")
        print(f"actual node types: {json.dumps(counts(actual_nodes), sort_keys=True)}\n")
        print("FIRST PROVEN DIVERGENCE\n")
        print(f"kind: {kind}")
        print(f"node_type: {culprit_type}")
        print(f"template_node_key: {node_key(culprit_node)}")
        print(f"in_degree: {context['in_degree']}")
        print(f"out_degree: {context['out_degree']}")
        print(f"neighbor types: {json.dumps(context['neighbor_types'])}")
        print(f"structural handles: {json.dumps(context['structural_handles'], sort_keys=True)}\n")
        for change_path, expected, actual in changes[:20]:
            structural = change_path.rsplit(".", 1)[-1] in {"sourceHandle", "targetHandle", "condition"}
            print(f"path: {change_path}")
            print(f"expected: {json.dumps(digest(expected, structural=structural), sort_keys=True)}")
            print(f"actual: {json.dumps(digest(actual, structural=structural), sort_keys=True)}\n")
        print(f"FIRST CHECKPOINT WHERE IT APPEARS:\n{first_checkpoint}\n")
        print(f"CAUSE CLASSIFICATION:\n{classification}\n")
        recommendation = ("Align the publisher normalization for the reported canonical path, then add the exact "
                          "candidate/snapshot pair as a regression fixture." if changes else
                          "No concrete direct-ID difference was proven; inspect the comparator pairing using this in-memory case.")
        print(f"RECOMMENDED MINIMAL FIX:\n{recommendation}\n")
        files = (["backend/app/flow_v2/publisher.py"] if classification == "PUBLISHER" else
                 ["backend/app/services/official_marketplace_template_service.py"])
        print(f"FILES THAT WOULD NEED TO CHANGE:\n{json.dumps(files)}\n")
        print("REGRESSION TEST REQUIRED:\nA focused structural-equivalence test for the reported path and value shapes.\n")
        print(f"structural_diff equivalent: {report['equivalent']}")
    finally:
        # This outer rollback is unconditional, including exceptions and Ctrl-C.
        db.rollback()
        if temporary_flow_id is not None:
            remaining_flows = db.scalar(select(func.count()).select_from(Flow).where(Flow.id == temporary_flow_id))
        if temporary_version_id is not None:
            remaining_versions = db.scalar(select(func.count()).select_from(FlowVersion).where(FlowVersion.id == temporary_version_id))
        db.rollback()
        db.close()
        print("\nTEMPORARY DB OBJECTS REMAINING:")
        print(f"temporary Flows remaining = {remaining_flows if remaining_flows >= 0 else 0}")
        print(f"temporary FlowVersions remaining = {remaining_versions if remaining_versions >= 0 else 0}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
