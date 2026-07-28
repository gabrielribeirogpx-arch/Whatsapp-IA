from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.flow_v2.publish_service import FlowV2PublishService
from app.models import Flow, FlowVersion, MarketplaceTemplate, MarketplaceTemplateVersion

STATUSES = {"draft", "preview_only", "published"}
MODALITIES = {"Sem IA", "Híbrido", "IA Completa", "Sistema Completo"}
SENSITIVE_KEYS = {
    "tenant_id", "flow_id", "session_id", "conversation_id", "contact_id", "user_id",
    "provider_id", "phone_number_id", "integration_id", "access_token", "refresh_token",
    "token", "credentials", "credential", "password", "secret", "api_key",
}
PLACEHOLDERS = {
    "tenant_id": "{{tenant.id}}", "flow_id": "{{flow.id}}", "contact_id": "{{contact.id}}",
    "provider_id": "{{provider.whatsapp}}", "phone_number_id": "{{provider.phone_number_id}}",
    "integration_id": "{{integration.connection}}",
}
PRIVATE_URL = re.compile(r"^https?://(?:localhost|127\.0\.0\.1|10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)", re.I)


def sanitize_snapshot(value: Any, key: str | None = None) -> Any:
    """Deep-copy the canonical contract, replacing only tenant-bound values."""
    if key in SENSITIVE_KEYS:
        return PLACEHOLDERS.get(key, "{{secret.configure_on_install}}")
    if isinstance(value, dict):
        return {k: sanitize_snapshot(v, k.lower()) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_snapshot(item, key) for item in value]
    if isinstance(value, str) and PRIVATE_URL.match(value):
        return "{{integration.private_url}}"
    return copy.deepcopy(value)


def remap_graph(nodes: list[dict], edges: list[dict]) -> tuple[list[dict], list[dict], dict[str, str]]:
    """Clone a graph and rewrite node references without touching option IDs/handles."""
    mapping = {str(node["id"]): str(uuid.uuid4()) for node in nodes}

    def rewrite(value: Any, key: str | None = None) -> Any:
        if isinstance(value, dict):
            return {k: rewrite(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [rewrite(v, key) for v in value]
        if isinstance(value, str) and value in mapping and key not in {"sourceHandle", "targetHandle", "source_handle", "target_handle", "option_id", "optionId"}:
            return mapping[value]
        return copy.deepcopy(value)

    return [rewrite(node) for node in nodes], [rewrite(edge) for edge in edges], mapping


def structural_diff(expected_nodes: list[dict], expected_edges: list[dict], actual_nodes: list[dict], actual_edges: list[dict], expected_start: str | None = None, actual_start: str | None = None) -> dict:
    """Compare logical graphs while ignoring regenerated graph IDs and timestamps."""
    ignored = {"created_at", "updated_at", "published_at", "timestamp"}

    def canonical(nodes: list[dict], edges: list[dict]) -> dict:
        aliases = {str(node.get("id")): f"node:{index}" for index, node in enumerate(nodes)}
        def clean(value: Any, key: str | None = None) -> Any:
            if key in ignored: return None
            if isinstance(value, dict): return {k: clean(v, k) for k, v in value.items() if k not in ignored}
            if isinstance(value, list): return [clean(v, key) for v in value]
            return aliases.get(value, value) if isinstance(value, str) and key not in {"sourceHandle", "targetHandle", "option_id", "optionId"} else value
        # Only graph-resource IDs are regenerated. Nested IDs (notably choice
        # option IDs) are part of the runtime contract and remain comparable.
        return {
            "nodes": [clean({k: v for k, v in n.items() if k != "id"}) for n in nodes],
            "edges": [clean({k: v for k, v in e.items() if k != "id"}) for e in edges],
        }

    expected, actual = canonical(expected_nodes, expected_edges), canonical(actual_nodes, actual_edges)
    differences = []
    if len(expected_nodes) != len(actual_nodes): differences.append({"path": "nodes.length", "expected": len(expected_nodes), "actual": len(actual_nodes)})
    if len(expected_edges) != len(actual_edges): differences.append({"path": "edges.length", "expected": len(expected_edges), "actual": len(actual_edges)})
    if expected_start is not None and actual_start is not None:
        expected_index = next((i for i, n in enumerate(expected_nodes) if str(n.get("id")) == str(expected_start)), None)
        actual_index = next((i for i, n in enumerate(actual_nodes) if str(n.get("id")) == str(actual_start)), None)
        if expected_index != actual_index: differences.append({"path": "start_node", "expected": expected_index, "actual": actual_index})
    for section in ("nodes", "edges"):
        for index, (left, right) in enumerate(zip(expected[section], actual[section])):
            if left != right: differences.append({"path": f"{section}[{index}]", "expected": left, "actual": right})
    return {"equivalent": not differences, "differences": differences, "counts": {"nodes": len(actual_nodes), "edges": len(actual_edges)}}


class OfficialMarketplaceTemplateService:
    def __init__(self, db: Session, tenant, user): self.db, self.tenant, self.user = db, tenant, user

    def _access(self):
        if self.user.role not in {"owner", "admin"} or str(self.user.tenant_id) != str(self.tenant.id):
            raise PermissionError("official_template_forbidden")

    def promote(self, flow_id, payload):
        self._access()
        if payload.status not in STATUSES or payload.modality not in MODALITIES: raise ValueError("invalid_template_metadata")
        flow = self.db.scalar(select(Flow).where(Flow.id == flow_id, Flow.tenant_id == self.tenant.id, Flow.is_deleted.is_(False)))
        if not flow or not flow.published_version_id: raise LookupError("published_flow_not_found")
        source = self.db.scalar(select(FlowVersion).where(FlowVersion.id == flow.published_version_id, FlowVersion.flow_id == flow.id, FlowVersion.is_published.is_(True)))
        if not source: raise LookupError("published_snapshot_not_found")
        snapshot = copy.deepcopy(source.snapshot or {})
        nodes = sanitize_snapshot(snapshot.get("nodes", source.nodes or []))
        edges = sanitize_snapshot(snapshot.get("edges", source.edges or []))
        start = snapshot.get("start_node_id") or source.start_node_id
        manifest = sanitize_snapshot({k: v for k, v in snapshot.items() if k not in {"nodes", "edges"}})
        manifest.update({"name": payload.name, "description": payload.description, "category": payload.category, "segment": payload.segment, "modality": payload.modality, "level": payload.level, "estimated_time": payload.estimated_time, "tags": payload.tags, "runtime": flow.runtime, "start_node_id": start})
        slug = payload.slug or re.sub(r"[^a-z0-9]+", "-", payload.name.lower()).strip("-")
        template = self.db.scalar(select(MarketplaceTemplate).where(MarketplaceTemplate.slug == slug))
        if template is None:
            template = MarketplaceTemplate(key=slug.replace("-", "_"), slug=slug, name=payload.name, description=payload.description, category=payload.category, segment=payload.segment, modality=payload.modality, created_by=self.user.id)
            self.db.add(template); self.db.flush()
        if self.db.scalar(select(MarketplaceTemplateVersion).where(MarketplaceTemplateVersion.template_id == template.id, MarketplaceTemplateVersion.version == payload.version)):
            raise ValueError("template_version_already_exists")
        canonical = json.dumps({"manifest": manifest, "nodes": nodes, "edges": edges}, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        report = structural_diff(nodes, edges, nodes, edges)
        version = MarketplaceTemplateVersion(template_id=template.id, version=payload.version, status=payload.status, source_flow_id=flow.id, source_flow_version_id=source.id, manifest=manifest, nodes_snapshot=nodes, edges_snapshot=edges, dependencies=manifest.get("dependencies", {}), checksum=hashlib.sha256(canonical.encode()).hexdigest(), validation_report=report, created_by=self.user.id, published_at=datetime.utcnow() if payload.status == "published" else None)
        self.db.add(version); self.db.commit(); self.db.refresh(version)
        return version

    def install(self, slug: str):
        self._access()
        version = self.db.scalar(select(MarketplaceTemplateVersion).join(MarketplaceTemplate).where(MarketplaceTemplate.slug == slug, MarketplaceTemplateVersion.status == "published").order_by(MarketplaceTemplateVersion.created_at.desc()))
        if not version: raise LookupError("published_template_not_found")
        nodes, edges, mapping = remap_graph(version.nodes_snapshot, version.edges_snapshot)
        flow = Flow(tenant_id=self.tenant.id, name=version.template.name, description=version.template.description, runtime=version.manifest.get("runtime", "v2"), status="draft", nodes=nodes, edges=edges, nodes_json=nodes, edges_json=edges)
        self.db.add(flow); self.db.flush()
        result = FlowV2PublishService().publish_draft(self.db, tenant_id=self.tenant.id, flow_id=flow.id)
        report = structural_diff(version.nodes_snapshot, version.edges_snapshot, result.snapshot["nodes"], result.snapshot["edges"], version.manifest.get("start_node_id"), result.snapshot.get("start_node_id"))
        if not report["equivalent"]: raise ValueError({"code": "installed_snapshot_diverged", "report": report})
        self.db.commit()
        return {"flow_id": str(flow.id), "flow_version_id": str(result.version.id), "template_version_id": str(version.id), "id_mapping": mapping, "validation": report, "post_install_route": f"/dashboard/flow-builder?flow_id={flow.id}"}

    def set_publication(self, version_id, publish: bool):
        self._access()
        version = self.db.get(MarketplaceTemplateVersion, version_id)
        if not version: raise LookupError("template_version_not_found")
        if publish and not version.validation_report.get("equivalent"):
            raise ValueError("template_has_functional_divergence")
        # Snapshots and manifests remain immutable; only catalog visibility is a
        # lifecycle property and can be toggled by an administrator.
        version.status = "published" if publish else "draft"
        version.published_at = datetime.utcnow() if publish else None
        self.db.commit(); self.db.refresh(version)
        return version
