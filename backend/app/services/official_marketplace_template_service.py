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
from app.flow_v2.publisher import resolve_runtime_v2_start_node_id
from app.flow_v2.node_handle_contract import migrate_edge_handles
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
CLINIC_NAME_TEXT_FIELDS = frozenset({"data.message", "data.content", "data.text"})
PRIVATE_URL = re.compile(r"^https?://(?:localhost|127\.0\.0\.1|10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)", re.I)
GOOGLE_CALENDAR_TOOLS = {
    "google_calendar_check_availability", "google_calendar_create_event",
    "google_calendar_find_managed_appointments", "google_calendar_update_event",
    "google_calendar_list_events", "calendar.get_availability",
    "calendar.create_appointment", "calendar.get_appointment",
    "calendar.reschedule_appointment", "calendar.cancel_appointment",
}

logger = logging.getLogger(__name__)

# These are routing-contract values, not business data. Only values in this
# closed set may be emitted verbatim by structural diagnostics.
SAFE_STRUCTURAL_VALUES = frozenset({
    "success", "error", "timeout", "selected", "empty", "cancel", "invalid",
    "true", "false", "default", "sucesso", "erro", "tempo_esgotado",
})


def _install_error_code(exc: Exception) -> str:
    if isinstance(exc, ValueError) and exc.args and isinstance(exc.args[0], dict):
        code = exc.args[0].get("code")
        if isinstance(code, str) and code:
            return code
    if exc.args and isinstance(exc.args[0], str) and exc.args[0]:
        return exc.args[0][:80]
    return type(exc).__name__


def _install_structural_log_fields(exc: Exception) -> tuple[str | None, str | None, str | None, str | None, str | None]:
    """Extract only allow-listed structural metadata from an install error."""
    payload = exc.args[0] if isinstance(exc, ValueError) and exc.args and isinstance(exc.args[0], dict) else {}
    report = payload.get("report") if isinstance(payload.get("report"), dict) else {}
    difference = (report.get("differences") or [{}])[0]
    if not isinstance(difference, dict):
        difference = {}
    expected_node = difference.get("expected_node") if isinstance(difference.get("expected_node"), dict) else {}
    actual_node = difference.get("candidate_node") if isinstance(difference.get("candidate_node"), dict) else {}
    return (
        difference.get("kind"), difference.get("path"),
        expected_node.get("type") or difference.get("node_type"), actual_node.get("type"),
        expected_node.get("template_node_key") or difference.get("template_node_key"),
    )


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
    if clinic.get("type") != "message" or mapping.clinic_name_field not in CLINIC_NAME_TEXT_FIELDS:
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


def publication_boundary_edges(nodes: list[dict], edges: list[dict]) -> list[dict]:
    """Return the Marketplace graph in the publisher's documented edge form.

    Installation used to compare the stored (possibly legacy) representation
    directly with the publisher output.  That made the comparison asymmetric:
    only the installed side had passed through ``migrate_edge_handles``.  Keep
    this deliberately narrow; it applies the same public boundary operation to
    the expected side and does not change endpoints or equate branch values.
    """
    return migrate_edge_handles(copy.deepcopy(nodes), copy.deepcopy(edges))


def publication_boundary_start_node_id(
    nodes: list[dict], edges: list[dict], declared_start_node_id: str | None = None
) -> str | None:
    """Return the candidate start identity in Runtime V2's canonical form.

    An explicit Marketplace identity remains authoritative (and is checked by
    ``structural_diff``).  Legacy candidates that omit it carry the same
    information on their start node, so resolve that marker through the exact
    publisher contract rather than treating absence as a wildcard.
    """
    if declared_start_node_id is not None:
        return str(declared_start_node_id)
    resolved = resolve_runtime_v2_start_node_id(nodes, edges)
    return resolved or None


def structural_diff(expected_nodes: list[dict], expected_edges: list[dict], actual_nodes: list[dict], actual_edges: list[dict], expected_start: str | None = None, actual_start: str | None = None) -> dict:
    """Compare attributed graphs up to a bijective renaming of graph IDs.

    Publication sorts UUID-bearing objects, so array position cannot identify a
    node.  Colour refinement supplies topology-aware candidate classes and the
    small constrained search below proves an exact isomorphism.  The final
    comparison includes every non-volatile node/edge property (including visual
    position, handles and conditions).
    """
    ignored = {"created_at", "updated_at", "published_at", "timestamp"}
    # FlowV2Publisher makes these security defaults explicit.  A missing value
    # and literal False have identical runtime meaning (only ``is True`` grants
    # either permission), so normalize precisely this publisher-created shape.
    # No other absent/null/default values are collapsed here.
    mcp_false_defaults = ("allow_external_write", "destructive_confirmed")

    def normalize_publisher_defaults(node: dict) -> dict:
        normalized = copy.deepcopy(node)
        data = normalized.get("data")
        if str(normalized.get("type") or "").lower() == "mcp_tool" and isinstance(data, dict):
            for field in mcp_false_defaults:
                data.setdefault(field, False)
        return normalized

    expected_nodes = [normalize_publisher_defaults(node) if isinstance(node, dict) else node for node in expected_nodes]
    actual_nodes = [normalize_publisher_defaults(node) if isinstance(node, dict) else node for node in actual_nodes]
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
        differences.append(_diagnose_structural_divergence(
            expected_nodes, expected_edges, actual_nodes, actual_edges, ignored,
        ))
    return {"equivalent": not differences, "differences": differences, "counts": {"nodes": len(actual_nodes), "edges": len(actual_edges)}}


def _diagnose_structural_divergence(expected_nodes, expected_edges, actual_nodes, actual_edges, ignored) -> dict:
    """Return one deterministic, production-safe explanation of a mismatch."""
    expected_ids = {str(node.get("id")) for node in expected_nodes if isinstance(node, dict)}
    actual_ids = {str(node.get("id")) for node in actual_nodes if isinstance(node, dict)}

    def identity(node):
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        result = {"type": str(node.get("type") or "")}
        key = data.get("template_node_key")
        if isinstance(key, str):
            result["template_node_key"] = key
        return result

    def safe_value(value, *, structural=False):
        if structural and isinstance(value, str) and value in SAFE_STRUCTURAL_VALUES:
            return {"safe_value": value}
        result = {"value_type": type(value).__name__}
        if isinstance(value, str):
            result.update(value_length=len(value), short_hash=hashlib.sha256(value.encode()).hexdigest()[:12])
        elif isinstance(value, (list, dict)):
            result["value_length"] = len(value)
        elif value is None or isinstance(value, (bool, int, float)):
            # Type is sufficient here: diagnostics must never accidentally
            # broaden their payload beyond the closed routing string set.
            pass
        return result

    def edge_fingerprint(source_identity, target_identity, field, source_signature=None, target_signature=None):
        # The signatures are hashes of canonical attributes and topology only.
        # They distinguish otherwise anonymous endpoints without ever exposing
        # message text, credentials, references, or other node payload values.
        material = json.dumps({"source": source_identity, "target": target_identity, "relation": field,
                               "source_signature": source_signature, "target_signature": target_signature},
                              sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(material.encode()).hexdigest()[:20]

    def structural_checkpoint(edge):
        data = edge.get("data") if isinstance(edge.get("data"), dict) else {}
        return {
            "sourceHandle": safe_value(edge.get("sourceHandle"), structural=True),
            "data.sourceHandle": safe_value(data.get("sourceHandle"), structural=True),
            "condition": safe_value(edge.get("condition"), structural=True),
            "data.condition": safe_value(data.get("condition"), structural=True),
        }

    def first_difference(left, right, path=""):
        if isinstance(left, dict) and isinstance(right, dict):
            keys = sorted((set(left) | set(right)) - ignored - ({"id"} if not path else set()))
            for key in keys:
                child = f"{path}.{key}" if path else key
                if key not in left or key not in right:
                    return child, left.get(key), right.get(key)
                found = first_difference(left[key], right[key], child)
                if found:
                    return found
            return None
        if isinstance(left, list) and isinstance(right, list):
            if len(left) != len(right):
                return path, left, right
            for index, (a, b) in enumerate(zip(left, right)):
                found = first_difference(a, b, f"{path}[{index}]")
                if found:
                    return found
            return None
        if isinstance(left, str) and isinstance(right, str) and left in expected_ids and right in actual_ids:
            # Both values are graph references. Their endpoint compatibility is
            # diagnosed from topology below, never from regenerated UUID text.
            return None
        return (path, left, right) if left != right else None

    def candidate_for(node):
        wanted = identity(node)
        keyed = [item for item in actual_nodes if isinstance(item, dict) and identity(item) == wanted]
        if len(keyed) == 1:
            return keyed[0]
        same_type = [item for item in actual_nodes if isinstance(item, dict) and str(item.get("type") or "") == wanted["type"]]
        position = node.get("position")
        positioned = [item for item in same_type if item.get("position") == position]
        return positioned[0] if len(positioned) == 1 else (same_type[0] if len(same_type) == 1 else None)

    for node in sorted((n for n in expected_nodes if isinstance(n, dict)), key=lambda n: json.dumps(identity(n), sort_keys=True)):
        candidate = candidate_for(node)
        if candidate is None:
            expected_count = sum(identity(item) == identity(node) for item in expected_nodes if isinstance(item, dict))
            actual_count = sum(identity(item) == identity(node) for item in actual_nodes if isinstance(item, dict))
            if expected_count != actual_count:
                return {"path": "graph", "kind": "unmatched_node_class", "node_type": identity(node)["type"],
                        "template_node_key": identity(node).get("template_node_key"), "expected_count": expected_count, "actual_count": actual_count}
            # Equal anonymous classes cannot safely be paired by array order.
            # Defer them to the topology-aware edge diagnostic below.
            continue
        found = first_difference(node, candidate)
        if found:
            field, expected, actual = found
            expected_ref = isinstance(expected, str) and expected in expected_ids
            actual_ref = isinstance(actual, str) and actual in actual_ids
            return {"path": f"nodes.{field}", "kind": "internal_reference_mismatch" if expected_ref or actual_ref else "node_attribute_mismatch",
                    "expected_node": identity(node), "candidate_node": identity(candidate), "field": field,
                    "expected": safe_value(expected), "actual": safe_value(actual)}

    # Attribute-compatible nodes but incompatible topology/edge payload.  This
    # deliberately uses an edge-label-free projection of the same canonical
    # graph information used by the isomorphism search.  Relation values are
    # omitted so that a single relation mismatch does not destroy endpoint
    # compatibility; canonical node attributes, degree and neighbourhood remain.
    expected_by_id = {str(n.get("id")): n for n in expected_nodes if isinstance(n, dict)}
    actual_by_id = {str(n.get("id")): n for n in actual_nodes if isinstance(n, dict)}

    def endpoint_signatures(nodes_by_id, edges, graph_ids):
        incoming, outgoing = defaultdict(list), defaultdict(list)
        for item in edges:
            if not isinstance(item, dict):
                continue
            source, target = str(item.get("source")), str(item.get("target"))
            if source in nodes_by_id and target in nodes_by_id:
                outgoing[source].append(target)
                incoming[target].append(source)

        def canonical_node(node):
            def clean(value, key=None):
                if isinstance(value, dict):
                    return {k: clean(v, k) for k, v in value.items() if k not in ignored and k != "id"}
                if isinstance(value, list):
                    return [clean(item, key) for item in value]
                if isinstance(value, str) and value in graph_ids and key not in {
                    "sourceHandle", "targetHandle", "source_handle", "target_handle", "option_id", "optionId",
                }:
                    return {"$node_ref": True}
                return value
            material = json.dumps(clean(node), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            return hashlib.sha256(material.encode()).hexdigest()

        base = {node_id: canonical_node(node) for node_id, node in nodes_by_id.items()}
        return {
            node_id: hashlib.sha256(json.dumps({
                "attribute": base[node_id],
                "in_degree": len(incoming[node_id]), "out_degree": len(outgoing[node_id]),
                "incoming": sorted(base[other] for other in incoming[node_id]),
                "outgoing": sorted(base[other] for other in outgoing[node_id]),
            }, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
            for node_id in nodes_by_id
        }

    expected_signatures = endpoint_signatures(expected_by_id, expected_edges, expected_ids)
    actual_signatures = endpoint_signatures(actual_by_id, actual_edges, actual_ids)

    def relation_payload(edge):
        return {k: v for k, v in edge.items() if k not in {"id", "source", "target"}}

    def all_differences(left, right, path=""):
        if isinstance(left, dict) and isinstance(right, dict):
            result = []
            for key in sorted((set(left) | set(right)) - ignored):
                child = f"{path}.{key}" if path else key
                if key not in left or key not in right:
                    result.append((child, left.get(key), right.get(key)))
                else:
                    result.extend(all_differences(left[key], right[key], child))
            return result
        if isinstance(left, list) and isinstance(right, list) and len(left) == len(right):
            return [item for index, pair in enumerate(zip(left, right))
                    for item in all_differences(pair[0], pair[1], f"{path}[{index}]")]
        return [] if left == right else [(path, left, right)]

    def ambiguous(source_identity, target_identity, candidates, source_signature, target_signature):
        return {"path": "edges.relation", "kind": "ambiguous_edge_pairing",
                "source_type": source_identity["type"],
                "source_template_node_key": source_identity.get("template_node_key"),
                "target_type": target_identity["type"],
                "target_template_node_key": target_identity.get("template_node_key"),
                "candidate_count": len(candidates),
                "edge_fingerprint": edge_fingerprint(source_identity, target_identity, "ambiguous",
                                                     source_signature, target_signature)}

    for edge in sorted((e for e in expected_edges if isinstance(e, dict)), key=lambda e: str(e.get("id") or "")):
        source_id, target_id = str(edge.get("source")), str(edge.get("target"))
        source, target = expected_by_id.get(source_id), expected_by_id.get(target_id)
        source_identity, target_identity = identity(source or {}), identity(target or {})
        source_signature, target_signature = expected_signatures.get(source_id), expected_signatures.get(target_id)
        candidates = [item for item in actual_edges if isinstance(item, dict)
                      and actual_signatures.get(str(item.get("source"))) == source_signature
                      and actual_signatures.get(str(item.get("target"))) == target_signature]
        comparisons = [(candidate, all_differences(relation_payload(edge), relation_payload(candidate)))
                       for candidate in candidates]
        if any(not changes for _, changes in comparisons):
            continue
        single_field = [(candidate, changes[0]) for candidate, changes in comparisons if len(changes) == 1]
        if len(single_field) == 1:
            candidate, (field, expected, actual) = single_field[0]
            structural = field in {"sourceHandle", "data.sourceHandle", "condition", "data.condition"}
            return {"path": f"edges.{field}", "kind": "edge_relation_mismatch",
                    "edge_fingerprint": edge_fingerprint(source_identity, target_identity, field,
                                                         source_signature, target_signature),
                    "source_type": source_identity["type"],
                    "source_template_node_key": source_identity.get("template_node_key"),
                    "target_type": target_identity["type"],
                    "target_template_node_key": target_identity.get("template_node_key"),
                    "field": field, "expected": safe_value(expected, structural=structural),
                    "actual": safe_value(actual, structural=structural),
                    "expected_checkpoint": structural_checkpoint(edge),
                    "actual_checkpoint": structural_checkpoint(candidate)}
        return ambiguous(source_identity, target_identity, candidates,
                         source_signature, target_signature)
    return {"path": "graph", "kind": "unmatched_node_class", "node_type": "unknown", "expected_count": len(expected_nodes), "actual_count": len(actual_nodes)}


class OfficialMarketplaceTemplateService:
    def __init__(self, db: Session, tenant, user): self.db, self.tenant, self.user = db, tenant, user

    def _access(self):
        if self.user.role not in {"owner", "admin"} or str(self.user.tenant_id) != str(self.tenant.id):
            raise PermissionError("official_template_forbidden")

    def promote(self, flow_id, payload):
        self._access()
        if payload.status not in STATUSES or payload.modality not in MODALITIES: raise ValueError("invalid_template_metadata")
        flow = self.db.scalar(select(Flow).where(Flow.id == flow_id, Flow.tenant_id == self.tenant.id, Flow.is_deleted.is_(False)))
        if not flow or not flow.current_version_id: raise LookupError("published_flow_not_found")
        # Saving in the Builder creates a new immutable FlowVersion and advances
        # current_version_id without publishing/activating it. Promotion must use
        # that saved snapshot rather than silently validating an older runtime
        # publication. Creating the Marketplace version has no effect on either
        # Flow publication pointer.
        source = self.db.scalar(select(FlowVersion).where(
            FlowVersion.id == flow.current_version_id,
            FlowVersion.flow_id == flow.id,
            FlowVersion.tenant_id == self.tenant.id,
        ))
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
        from app.services.template_certification_service import TemplateCertificationService, candidate_checksum
        certification = TemplateCertificationService(self.db, tenant_id=self.tenant.id).certify(
            manifest=manifest, nodes=nodes, edges=edges,
        )
        if not certification.ok:
            self.db.rollback()
            raise ValueError({"code": "template_certification_failed", "stage": certification.stage,
                              "issues": list(certification.issues)})
        checksum = candidate_checksum(manifest, nodes, edges)
        if checksum != certification.candidate_checksum:
            self.db.rollback()
            raise ValueError("template_candidate_checksum_mismatch")
        # `status=published` is only a request. Certification, not the client,
        # authorizes the server-owned lifecycle transition.
        status = "published" if payload.status == "published" else payload.status
        report = certification.report()
        version = MarketplaceTemplateVersion(template_id=template.id, version=payload.version, status=status, source_flow_id=flow.id, source_flow_version_id=source.id, manifest=manifest, nodes_snapshot=nodes, edges_snapshot=edges, dependencies=manifest.get("dependencies", {}), checksum=checksum, validation_report=report, certification_status="certified", certification_version=certification.certification_version, candidate_checksum=certification.candidate_checksum, certified_at=datetime.fromisoformat(certification.certified_at), created_by=self.user.id, published_at=datetime.utcnow() if status == "published" else None)
        self.db.add(version); self.db.commit(); self.db.refresh(version)
        return version

    def install(self, slug: str, version_id=None):
        self._access()
        filters = [
            MarketplaceTemplate.slug == slug,
            MarketplaceTemplateVersion.status == "published",
            MarketplaceTemplateVersion.certification_status.in_(("certified", "legacy_unverified")),
        ]
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
            expected_edges = publication_boundary_edges(version.nodes_snapshot, version.edges_snapshot)
            expected_start = publication_boundary_start_node_id(
                version.nodes_snapshot, version.edges_snapshot,
                version.manifest.get("start_node_id"),
            )
            report = structural_diff(version.nodes_snapshot, expected_edges, result.snapshot["nodes"], result.snapshot["edges"], expected_start, result.snapshot.get("start_node_id"))
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
            diff_kind, diff_path, expected_type, actual_type, template_node_key = _install_structural_log_fields(exc)
            logger.exception(
                "event=official_marketplace_install_failed template_slug=%s "
                "template_version_id=%s tenant_id=%s stage=%s error_code=%s "
                "structural_diff_kind=%s structural_diff_path=%s expected_node_type=%s "
                "actual_node_type=%s template_node_key=%s",
                slug, version.id, self.tenant.id, stage, _install_error_code(exc),
                diff_kind, diff_path, expected_type, actual_type, template_node_key,
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
        if publish:
            from app.services.template_certification_service import CERTIFICATION_VERSION, candidate_checksum
            expected = candidate_checksum(version.manifest, version.nodes_snapshot, version.edges_snapshot)
            if not (version.certification_status == "certified"
                    and version.certification_version == CERTIFICATION_VERSION
                    and version.candidate_checksum == expected
                    and version.validation_report.get("ok") is True):
                raise ValueError("template_certification_required")
        # Snapshots and manifests remain immutable; only catalog visibility is a
        # lifecycle property and can be toggled by an administrator.
        version.status = "published" if publish else "draft"
        version.published_at = datetime.utcnow() if publish else None
        self.db.commit(); self.db.refresh(version)
        return version
