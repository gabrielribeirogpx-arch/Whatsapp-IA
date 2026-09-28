"""Fail-closed certification of Marketplace graphs through Runtime V2."""
from __future__ import annotations

import copy
import hashlib
import json
import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.flow_v2.graph_validator import FlowV2GraphValidator
from app.flow_v2.publish_service import FlowV2PublishService
from app.models import Flow
from app.services.assistant_configuration_service import CAPABILITY
from app.services.assistant_materialization_service import _contract

CERTIFICATION_VERSION = "template-certification-v1"
logger = logging.getLogger(__name__)


def candidate_checksum(manifest: dict, nodes: list, edges: list) -> str:
    canonical = json.dumps({"manifest": manifest, "nodes": nodes, "edges": edges},
                           sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class TemplateCertificationResult:
    ok: bool
    certification_version: str
    candidate_checksum: str
    runtime_snapshot_hash: str | None
    stage: str
    issues: tuple[dict[str, Any], ...]
    canonical_summary: dict[str, Any]
    certified_at: str | None = None

    def report(self) -> dict[str, Any]:
        return asdict(self)


class TemplateCertificationService:
    """Certify a final commercial candidate without retaining dry-run rows."""

    def __init__(self, db: Session, *, tenant_id) -> None:
        self.db = db
        self.tenant_id = tenant_id

    def certify(self, *, manifest: dict, nodes: list, edges: list) -> TemplateCertificationResult:
        # Import the canonical Marketplace operations lazily to avoid moving or
        # forking their established contracts.
        from app.services.official_marketplace_template_service import (
            publication_boundary_edges, publication_boundary_start_node_id,
            remap_graph, structural_diff,
        )

        checksum = candidate_checksum(manifest, nodes, edges)
        summary = {"nodes": len(nodes), "edges": len(edges), "capabilities": len(manifest.get("capabilities", []))}

        validation = FlowV2GraphValidator().validate(nodes=nodes, edges=edges)
        if not validation.is_valid:
            return self._fail(checksum, "static_validation", "template_graph_invalid", summary,
                              count=len(validation.errors))

        if CAPABILITY in manifest.get("capabilities", []):
            try:
                _contract(type("CertificationCandidate", (), {"manifest": manifest})())
            except HTTPException as exc:
                code = exc.detail if isinstance(exc.detail, str) else "invalid_materialization_contract"
                return self._fail(checksum, "capability_contract", code, summary)

        try:
            remapped_nodes, remapped_edges, mapping = remap_graph(nodes, edges)
            expected_start = (
                mapping.get(str(manifest["start_node_id"]))
                if manifest.get("start_node_id") is not None else None
            )
        except (KeyError, TypeError, ValueError):
            return self._fail(checksum, "remap", "template_remap_failed", summary)

        savepoint = self.db.begin_nested()
        try:
            temporary = Flow(
                id=uuid.uuid4(), tenant_id=self.tenant_id,
                name=f"template-certification-{uuid.uuid4().hex}", runtime="v2", status="draft",
                nodes=copy.deepcopy(remapped_nodes), edges=copy.deepcopy(remapped_edges),
                nodes_json=copy.deepcopy(remapped_nodes), edges_json=copy.deepcopy(remapped_edges),
            )
            self.db.add(temporary)
            self.db.flush()
            published = FlowV2PublishService().publish_draft(
                self.db, tenant_id=self.tenant_id, flow_id=temporary.id,
            )
            snapshot = copy.deepcopy(published.snapshot)
            runtime_hash = published.version.v2_snapshot_hash
        except Exception:
            savepoint.rollback()
            return self._fail(checksum, "runtime_publish", "template_runtime_publish_failed", summary)
        finally:
            if savepoint.is_active:
                savepoint.rollback()

        expected_edges = publication_boundary_edges(remapped_nodes, remapped_edges)
        expected_start = publication_boundary_start_node_id(
            remapped_nodes, remapped_edges, expected_start
        )
        report = structural_diff(remapped_nodes, expected_edges, snapshot["nodes"], snapshot["edges"],
                                 expected_start, snapshot.get("start_node_id"))
        if not report["equivalent"]:
            difference = (report.get("differences") or [{}])[0]
            issue = {key: difference[key] for key in (
                "path", "kind", "node_type", "template_node_key", "field", "edge_fingerprint",
                "source_type", "source_template_node_key", "target_type", "target_template_node_key",
                "expected", "actual", "candidate_count",
            ) if key in difference and difference[key] is not None}
            issue["code"] = "template_snapshot_diverged"
            if difference.get("kind") in {"edge_relation_mismatch", "ambiguous_edge_pairing"}:
                log_payload = {
                    "event": "template_certification_structural_mismatch",
                    "certification_version": CERTIFICATION_VERSION,
                    "candidate_checksum": checksum,
                    "stage": "structural_equivalence",
                    **{key: difference[key] for key in (
                        "kind", "path", "edge_fingerprint", "source_type", "source_template_node_key",
                        "target_type", "target_template_node_key", "expected_checkpoint", "actual_checkpoint",
                        "candidate_count",
                    ) if key in difference and difference[key] is not None},
                }
                logger.warning("template_certification_structural_mismatch %s",
                               json.dumps(log_payload, sort_keys=True, separators=(",", ":")))
            return TemplateCertificationResult(False, CERTIFICATION_VERSION, checksum, runtime_hash,
                                               "structural_equivalence", (issue,), summary)
        return TemplateCertificationResult(True, CERTIFICATION_VERSION, checksum, runtime_hash, "pass", (), summary,
                                           datetime.utcnow().isoformat())

    @staticmethod
    def _fail(checksum: str, stage: str, code: str, summary: dict, **safe: Any) -> TemplateCertificationResult:
        return TemplateCertificationResult(False, CERTIFICATION_VERSION, checksum, None, stage,
                                           ({"code": code, **safe},), summary)
