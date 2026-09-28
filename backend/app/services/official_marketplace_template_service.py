from __future__ import annotations

import copy
import hashlib
import json
import logging
import re
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.flow_v2.publish_service import FlowV2PublishService
from app.models import (
    Flow,
    FlowVersion,
    MarketplaceInstallation,
    MarketplaceInstallationResource,
    MarketplaceTemplate,
    MarketplaceTemplateVersion,
)
from app.models.audit_log import AuditLog
from app.services.assistant_flow_management_service import establish_official_baseline
from app.services.assistant_configuration_service import CAPABILITY
from app.services.assistant_materialization_service import _contract

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
GOOGLE_CALENDAR_TOOLS = {
    "google_calendar_check_availability", "google_calendar_create_event",
    "google_calendar_find_managed_appointments", "google_calendar_update_event",
    "google_calendar_list_events", "calendar.get_availability",
    "calendar.create_appointment", "calendar.get_appointment",
    "calendar.reschedule_appointment", "calendar.cancel_appointment",
}

logger = logging.getLogger(__name__)


def _install_error_code(exc: Exception) -> str:
    if isinstance(exc, ValueError) and exc.args and isinstance(exc.args[0], dict):
        code = exc.args[0].get("code")
        if isinstance(code, str) and code:
            return code
    if exc.args and isinstance(exc.args[0], str) and exc.args[0]:
        return exc.args[0][:80]
    return type(exc).__name__


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


def _assistant_contract(nodes: list[dict], mapping) -> tuple[list[dict], dict]:
    """Validate an explicit product mapping and enrich only its snapshot copy."""
    if not mapping.calendar_node_ids:
        raise ValueError("assistant_calendar_mapping_required")
    if not mapping.handoff_node_ids:
        raise ValueError("assistant_handoff_mapping_required")
    by_id = {str(node.get("id")): node for node in nodes if isinstance(node, dict)}
    selected_ids = [str(mapping.clinic_name_node_id), str(mapping.services_node_id)]
    selected_ids += [str(value) for value in mapping.calendar_node_ids]
    selected_ids += [str(value) for value in mapping.handoff_node_ids]
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError("assistant_mapping_node_roles_must_be_unique")
    if any(node_id not in by_id for node_id in selected_ids):
        raise ValueError("assistant_mapping_node_not_found")
    if len(mapping.calendar_node_ids) != len(set(mapping.calendar_node_ids)) or len(mapping.handoff_node_ids) != len(set(mapping.handoff_node_ids)):
        raise ValueError("assistant_mapping_duplicate_node")

    clinic = by_id[str(mapping.clinic_name_node_id)]
    if clinic.get("type") != "message" or mapping.clinic_name_field not in {"data.message", "data.content", "data.text"}:
        raise ValueError("assistant_clinic_name_target_invalid")
    clinic_field = mapping.clinic_name_field.split(".", 1)[1]
    if not isinstance(clinic.get("data"), dict) or clinic_field not in clinic["data"]:
        raise ValueError("assistant_clinic_name_target_invalid")
    clinic_message = clinic["data"][clinic_field]
    if not isinstance(clinic_message, str) or "{{clinic_name}}" not in clinic_message:
        raise ValueError("assistant_clinic_name_placeholder_missing")

    services = by_id[str(mapping.services_node_id)]
    services_data = services.get("data") if isinstance(services.get("data"), dict) else {}
    result_variable = services_data.get("result_variable")
    if services.get("type") != "choice" or services_data.get("options_mode", "fixed") != "fixed":
        raise ValueError("assistant_services_target_invalid")
    if not isinstance(result_variable, str) or not result_variable.strip() or len(result_variable.strip()) > 120:
        raise ValueError("assistant_service_selection_variable_invalid")

    calendars = [by_id[str(value)] for value in mapping.calendar_node_ids]
    for node in calendars:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        if node.get("type") != "mcp_tool" or data.get("tool_name") not in GOOGLE_CALENDAR_TOOLS or "connection_id" not in data:
            raise ValueError("assistant_calendar_target_invalid")
    handoffs = [by_id[str(value)] for value in mapping.handoff_node_ids]
    for node in handoffs:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        if node.get("type") != "action" or data.get("action_type", data.get("action")) != "transfer_human" or "reason" not in data:
            raise ValueError("assistant_handoff_target_invalid")

    roles = [(clinic, "clinic_name", mapping.clinic_name_field, "assistant.clinic_name"),
             (services, "services", "data.options", "assistant.services")]
    roles += [(node, "google_calendar_connection_id", "data.connection_id", f"assistant.calendar.{index + 1}") for index, node in enumerate(calendars)]
    roles += [(node, "handoff.reason", "data.reason", f"assistant.handoff.{index + 1}") for index, node in enumerate(handoffs)]
    assigned_keys = {key for _, _, _, key in roles}
    for node in nodes:
        key = (node.get("data") or {}).get("template_node_key") if isinstance(node, dict) else None
        if key in assigned_keys and all(node is not selected for selected, _, _, _ in roles):
            raise ValueError("assistant_template_node_key_duplicate")
    targets = []
    for node, parameter, field, key in roles:
        node.setdefault("data", {})["template_node_key"] = key
        if parameter == "google_calendar_connection_id":
            node["data"]["connection_id"] = "{{integration.connection}}"
        target = {"parameter": parameter, "node_key": key, "field": field}
        if parameter == "clinic_name":
            target["operation"] = "interpolate"
        targets.append(target)
    final_keys = [
        node.get("data", {}).get("template_node_key") for node in nodes
        if isinstance(node, dict) and isinstance(node.get("data"), dict)
        and isinstance(node["data"].get("template_node_key"), str)
    ]
    if len(final_keys) != len(set(final_keys)):
        raise ValueError("assistant_template_node_key_duplicate")
    contract = {"schema_version": 1, "service_selection_variable": result_variable.strip(), "targets": targets}
    # Reuse the materializer's canonical parser before persisting anything.
    _contract(type("PromotionVersion", (), {"manifest": {"capabilities": [CAPABILITY], "assistant_materialization": contract}})())
    return nodes, contract


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
    """Compare attributed graphs up to a bijective renaming of graph IDs.

    Publication sorts UUID-bearing objects, so array position cannot identify a
    node.  Colour refinement supplies topology-aware candidate classes and the
    small constrained search below proves an exact isomorphism.  The final
    comparison includes every non-volatile node/edge property (including visual
    position, handles and conditions).
    """
    ignored = {"created_at", "updated_at", "published_at", "timestamp"}
    differences = []
    if len(expected_nodes) != len(actual_nodes): differences.append({"path": "nodes.length", "expected": len(expected_nodes), "actual": len(actual_nodes)})
    if len(expected_edges) != len(actual_edges): differences.append({"path": "edges.length", "expected": len(expected_edges), "actual": len(actual_edges)})
    if differences:
        return {"equivalent": False, "differences": differences, "counts": {"nodes": len(actual_nodes), "edges": len(actual_edges)}}

    def graph(nodes: list[dict], edges: list[dict], start: str | None):
        ids = [str(node.get("id")) for node in nodes]
        if len(ids) != len(set(ids)):
            return None
        id_set = set(ids)
        relations: list[tuple[str, str, str]] = []

        def clean(value: Any, key: str | None = None, path: str = "") -> Any:
            if isinstance(value, dict):
                return {k: clean(v, k, f"{path}.{k}") for k, v in value.items() if k not in ignored}
            if isinstance(value, list):
                return [clean(v, key, f"{path}[{i}]") for i, v in enumerate(value)]
            if isinstance(value, str) and value in id_set and key not in {"sourceHandle", "targetHandle", "source_handle", "target_handle", "option_id", "optionId"}:
                return {"$node_ref": path}
            return value

        attrs = {}
        for node in nodes:
            node_id = str(node["id"])
            attrs[node_id] = json.dumps(clean({k: v for k, v in node.items() if k != "id"}), sort_keys=True, separators=(",", ":"), ensure_ascii=False)

            def references(value: Any, key: str | None = None, path: str = "node") -> None:
                if isinstance(value, dict):
                    for k, v in value.items():
                        if k not in ignored and k != "id": references(v, k, f"{path}.{k}")
                elif isinstance(value, list):
                    for i, item in enumerate(value): references(item, key, f"{path}[{i}]")
                elif isinstance(value, str) and value in id_set and key not in {"sourceHandle", "targetHandle", "source_handle", "target_handle", "option_id", "optionId"}:
                    relations.append((node_id, value, f"ref:{path}"))
            references(node)

        for edge in edges:
            source, target = str(edge.get("source")), str(edge.get("target"))
            if source not in id_set or target not in id_set:
                return None
            label = json.dumps(clean({k: v for k, v in edge.items() if k not in {"id", "source", "target"}}), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            relations.append((source, target, f"edge:{label}"))
        return ids, attrs, relations, str(start) if start is not None else None

    left, right = graph(expected_nodes, expected_edges, expected_start), graph(actual_nodes, actual_edges, actual_start)
    mapping = None
    if left is not None and right is not None:
        left_ids, left_attrs, left_rel, left_start = left
        right_ids, right_attrs, right_rel, right_start = right
        left_colors = {node: (left_attrs[node], node == left_start) for node in left_ids}
        right_colors = {node: (right_attrs[node], node == right_start) for node in right_ids}
        for _ in range(len(left_ids) + 1):
            combined = [("l", left_ids, left_colors, left_rel), ("r", right_ids, right_colors, right_rel)]
            # A shared palette is essential: independently numbered colours are not comparable.
            signatures = {}
            for side, ids, colors, relations in combined:
                incoming, outgoing = defaultdict(list), defaultdict(list)
                for source, target, label in relations:
                    outgoing[source].append((label, colors[target])); incoming[target].append((label, colors[source]))
                for node in ids: signatures[(side, node)] = (colors[node], tuple(sorted(outgoing[node])), tuple(sorted(incoming[node])))
            palette = {signature: index for index, signature in enumerate(sorted(set(signatures.values()), key=repr))}
            next_left = {node: palette[signatures[("l", node)]] for node in left_ids}
            next_right = {node: palette[signatures[("r", node)]] for node in right_ids}
            if next_left == left_colors and next_right == right_colors: break
            left_colors, right_colors = next_left, next_right

        if Counter(left_colors.values()) == Counter(right_colors.values()):
            right_by_color = defaultdict(list)
            for node in right_ids: right_by_color[right_colors[node]].append(node)
            left_rel_count, right_rel_count = Counter(left_rel), Counter(right_rel)
            relation_labels = {relation[2] for relation in left_rel + right_rel}

            def exact_payload_match(candidate_mapping: dict[str, str]) -> bool:
                inverse = {actual: expected for expected, actual in candidate_mapping.items()}

                def canonical(nodes, edges, aliases):
                    def clean(value: Any, key: str | None = None) -> Any:
                        if isinstance(value, dict):
                            return {k: clean(v, k) for k, v in value.items() if k not in ignored}
                        if isinstance(value, list): return [clean(item, key) for item in value]
                        if isinstance(value, str) and value in aliases and key not in {"sourceHandle", "targetHandle", "source_handle", "target_handle", "option_id", "optionId"}:
                            return aliases[value]
                        return value
                    normalized_nodes = [clean(node) for node in nodes]
                    normalized_edges = [clean({k: v for k, v in edge.items() if k != "id"}) for edge in edges]
                    return (sorted(normalized_nodes, key=lambda item: str(item.get("id"))),
                            sorted(normalized_edges, key=lambda item: json.dumps(item, sort_keys=True, ensure_ascii=False)))

                expected_aliases = {node: node for node in left_ids}
                return canonical(expected_nodes, expected_edges, expected_aliases) == canonical(actual_nodes, actual_edges, inverse)

            def search(current: dict[str, str]) -> dict[str, str] | None:
                if len(current) == len(left_ids):
                    mapped = Counter((current[s], current[t], label) for s, t, label in left_rel)
                    return current if mapped == right_rel_count and exact_payload_match(current) else None
                unused = set(right_ids) - set(current.values())
                node = min((n for n in left_ids if n not in current), key=lambda n: sum(c in unused for c in right_by_color[left_colors[n]]))
                for candidate in sorted(right_by_color[left_colors[node]]):
                    if candidate not in unused: continue
                    trial = {**current, node: candidate}
                    if all(left_rel_count[(a, b, label)] == right_rel_count[(trial[a], trial[b], label)]
                           for a in trial for b in trial for label in relation_labels):
                        found = search(trial)
                        if found is not None: return found
                return None
            mapping = search({})

    if mapping is None:
        differences.append({"path": "graph", "expected": "isomorphic attributed graph", "actual": "structural divergence"})
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
        if payload.template_kind not in {"flow", "appointment_assistant"}:
            raise ValueError("invalid_template_kind")
        if payload.template_kind == "flow" and payload.assistant_mapping is not None:
            raise ValueError("assistant_mapping_not_allowed")
        if payload.template_kind == "appointment_assistant":
            if payload.assistant_mapping is None:
                raise ValueError("assistant_mapping_required")
            nodes, contract = _assistant_contract(nodes, payload.assistant_mapping)
            capabilities = manifest.get("capabilities", [])
            capabilities = list(capabilities) if isinstance(capabilities, list) else []
            manifest["capabilities"] = list(dict.fromkeys([*capabilities, CAPABILITY]))
            manifest["assistant_materialization"] = contract
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

    def install(self, slug: str, version_id=None):
        self._access()
        filters = [MarketplaceTemplate.slug == slug, MarketplaceTemplateVersion.status == "published"]
        if version_id is not None:
            filters.append(MarketplaceTemplateVersion.id == version_id)
        version = self.db.scalar(select(MarketplaceTemplateVersion).join(MarketplaceTemplate).where(*filters).order_by(MarketplaceTemplateVersion.created_at.desc()))
        if not version: raise LookupError("published_template_not_found")
        stage = "clone_graph"
        try:
            nodes, edges, mapping = remap_graph(version.nodes_snapshot, version.edges_snapshot)
            stage = "create_installation"
            installation = MarketplaceInstallation(
                tenant_id=self.tenant.id,
                # These two legacy columns intentionally retain their textual
                # slug/version semantics. Canonical UUIDs live on the resource.
                template_id=version.template.slug,
                template_slug=version.template.slug,
                template_type="official_flow",
                template_version=version.version,
                automation_level="official",
                variant=version.template.modality,
                status="pending",
                idempotency_key=f"official:{uuid.uuid4()}",
                installed_by_user_id=self.user.id,
                manifest_snapshot=copy.deepcopy(version.manifest),
                dependency_snapshot=copy.deepcopy(version.dependencies or {}),
                customization_state={},
                created_resources={},
            )
            self.db.add(installation); self.db.flush()
            stage = "create_flow"
            flow = Flow(tenant_id=self.tenant.id, name=version.template.name, description=version.template.description, runtime=version.manifest.get("runtime", "v2"), status="draft", nodes=nodes, edges=edges, nodes_json=nodes, edges_json=edges)
            self.db.add(flow); self.db.flush()
            stage = "publish_initial_flow_version"
            result = FlowV2PublishService().publish_draft(self.db, tenant_id=self.tenant.id, flow_id=flow.id)
            stage = "validate_installed_snapshot"
            report = structural_diff(version.nodes_snapshot, version.edges_snapshot, result.snapshot["nodes"], result.snapshot["edges"], version.manifest.get("start_node_id"), result.snapshot.get("start_node_id"))
            if not report["equivalent"]: raise ValueError({"code": "installed_snapshot_diverged", "report": report})
            stage = "create_provenance"
            resource = MarketplaceInstallationResource(
                installation_id=installation.id,
                resource_type="flow",
                resource_id=str(flow.id),
                resource_name=flow.name,
                creation_status="created",
                metadata_json={
                    "ownership": str(installation.id),
                    "template_id": str(version.template_id),
                    "template_version_id": str(version.id),
                    "generated_flow_version_id": str(result.version.id),
                },
            )
            self.db.add(resource)
            stage = "establish_managed_baseline"
            establish_official_baseline(
                self.db, installation=installation, flow=flow,
                flow_version=result.version, checksum=result.version.graph_checksum,
            )
            assistant = CAPABILITY in version.manifest.get("capabilities", [])
            post_install_route = (f"/dashboard/assistants/appointments/{installation.id}" if assistant
                                  else f"/dashboard/flow-builder?flow_id={flow.id}")
            installation.created_resources = {"flows": [str(flow.id)], "post_install_route": post_install_route}
            installation.status = "completed"
            installation.completed_at = datetime.utcnow()
            self.db.add(AuditLog(
                tenant_id=self.tenant.id,
                user_id=self.user.id,
                action="template_install_completed",
                entity_type="marketplace_installation",
                entity_id=str(installation.id),
                metadata_json={
                    "installation_id": str(installation.id),
                    "template_id": str(version.template_id),
                    "template_version_id": str(version.id),
                    "flow_id": str(flow.id),
                    "flow_version_id": str(result.version.id),
                },
            ))
            stage = "commit"
            self.db.commit()
            return {"installation_id": str(installation.id), "flow_id": str(flow.id), "flow_version_id": str(result.version.id), "template_version_id": str(version.id), "id_mapping": mapping, "validation": report, "post_install_route": post_install_route}
        except Exception as exc:
            # Installation, flow, initial version, provenance resource and audit
            # record form one unit. Never retain a partially installed template.
            self.db.rollback()
            logger.exception(
                "event=official_marketplace_install_failed template_slug=%s "
                "template_version_id=%s tenant_id=%s stage=%s error_code=%s",
                slug, version.id, self.tenant.id, stage, _install_error_code(exc),
            )
            raise

    def get_provenance(self, installation_id) -> dict:
        """Resolve official provenance without guessing for legacy installations."""
        installation = self.db.scalar(select(MarketplaceInstallation).where(
            MarketplaceInstallation.id == installation_id,
            MarketplaceInstallation.tenant_id == self.tenant.id,
        ))
        if installation is None:
            raise LookupError("installation_not_found")
        resource = next((item for item in installation.resources if item.resource_type == "flow"), None)
        metadata = resource.metadata_json if resource and isinstance(resource.metadata_json, dict) else {}

        def parsed_uuid(key):
            try:
                return uuid.UUID(str(metadata[key]))
            except (KeyError, TypeError, ValueError, AttributeError):
                return None

        template_id = parsed_uuid("template_id")
        template_version_id = parsed_uuid("template_version_id")
        try:
            flow_id = uuid.UUID(resource.resource_id) if resource else None
        except (TypeError, ValueError, AttributeError):
            flow_id = None
        flow_version_id = parsed_uuid("generated_flow_version_id")
        template = self.db.get(MarketplaceTemplate, template_id) if template_id else None
        version = self.db.get(MarketplaceTemplateVersion, template_version_id) if template_version_id else None
        flow = self.db.get(Flow, flow_id) if flow_id else None
        flow_version = self.db.get(FlowVersion, flow_version_id) if flow_version_id else None
        valid = bool(
            template and version and flow and flow_version
            and version.template_id == template.id
            and flow.tenant_id == self.tenant.id
            and flow_version.flow_id == flow.id
        )
        return {
            "installation": installation,
            "template": template if valid else None,
            "template_version": version if valid else None,
            "flow": flow if valid else None,
            "generated_flow_version": flow_version if valid else None,
            "legacy_or_unknown": not valid,
        }

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
