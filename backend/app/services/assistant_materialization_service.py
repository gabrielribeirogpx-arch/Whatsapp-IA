"""Controlled AssistantConfiguration -> ordinary FlowVersion materialization.

The template version owns both stable ``data.template_node_key`` values and the
``manifest.assistant_materialization`` target list.  The HTTP client supplies
only optimistic-concurrency values; it can never select graph destinations.
"""
from __future__ import annotations

import copy
from datetime import datetime
from typing import Any
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Flow, MarketplaceTemplateVersion
from app.models.integration_connection import IntegrationConnection
from app.models.marketplace_installation import (
    AssistantCalendarBinding,
    MarketplaceInstallationAssistantConfiguration,
    MarketplaceInstallationFlowManagement,
)
from app.schemas.assistant_configuration import AssistantConfigurationV1, AssistantMaterializationRequest
from app.services.assistant_configuration_service import CAPABILITY, get_installation_for_configuration
from app.services.assistant_calendar_binding_service import binding_is_valid
from app.services.assistant_flow_management_service import assert_managed_flow_baseline
from app.services.audit_service import write_audit_log
from app.services.flow_engine_service import flow_version_nodes_edges, graph_hash, validate_flow_graph
from app.services.flow_service import FlowService


CONTRACT_KEY = "assistant_materialization"
ALLOWED_TARGETS = {
    "clinic_name": {"data.message", "data.content", "data.text"},
    "services": {"data.options"},
    "google_calendar_connection_id": {"data.connection_id"},
    "handoff.reason": {"data.reason"},
}
DEFAULT_OPERATION = "replace"
ALLOWED_OPERATIONS = {DEFAULT_OPERATION, "interpolate"}


def _materialized_services(
    configuration: AssistantConfigurationV1, source_node: dict[str, Any],
) -> list[dict[str, str]]:
    """Keep configured identities while carrying forward template routing handles."""
    source_data = source_node.get("data") if isinstance(source_node.get("data"), dict) else {}
    source_options = source_data.get("options")
    historical = [option for option in source_options if isinstance(option, dict)] if isinstance(source_options, list) else []

    def unique_match(key: str, value: str) -> dict[str, Any] | None:
        matches = [option for option in historical if option.get(key) == value]
        return matches[0] if len(matches) == 1 else None

    materialized: list[dict[str, str]] = []
    for service in configuration.services:
        option = {"id": service.id, "label": service.label, "value": service.id}
        original = unique_match("id", service.id) or unique_match("value", service.id)
        if original is None:
            original = unique_match("label", service.label)
        if original is not None:
            for handle_key in ("source_handle", "sourceHandle"):
                handle = original.get(handle_key)
                if isinstance(handle, str) and handle:
                    option[handle_key] = handle
        materialized.append(option)
    return materialized


def _uuid(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def _contract(version: MarketplaceTemplateVersion) -> list[dict[str, str]]:
    manifest = version.manifest if isinstance(version.manifest, dict) else {}
    raw = manifest.get(CONTRACT_KEY)
    if not isinstance(raw, dict) or raw.get("schema_version") != 1:
        raise HTTPException(422, "template_does_not_support_materialization")
    variable = raw.get("service_selection_variable")
    if not isinstance(variable, str) or not variable.strip() or len(variable) > 120:
        raise HTTPException(422, "invalid_materialization_contract")
    if CAPABILITY not in manifest.get("capabilities", []):
        raise HTTPException(422, "template_does_not_support_materialization")
    targets = raw.get("targets")
    if not isinstance(targets, list) or not targets:
        raise HTTPException(422, "invalid_materialization_contract")
    result: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for target in targets:
        if not isinstance(target, dict) or not {"parameter", "node_key", "field"} <= set(target) or set(target) - {"parameter", "node_key", "field", "operation"}:
            raise HTTPException(422, "invalid_materialization_contract")
        parameter, node_key, field = target.get("parameter"), target.get("node_key"), target.get("field")
        if parameter not in ALLOWED_TARGETS or field not in ALLOWED_TARGETS[parameter]:
            raise HTTPException(422, "materialization_target_not_allowed")
        if not isinstance(node_key, str) or not node_key.strip() or len(node_key) > 120:
            raise HTTPException(422, "invalid_materialization_contract")
        operation = target.get("operation", DEFAULT_OPERATION)
        if operation not in ALLOWED_OPERATIONS or (operation == "interpolate" and parameter != "clinic_name"):
            raise HTTPException(422, "materialization_operation_not_allowed")
        identity = (parameter, node_key, field)
        if identity in seen:
            raise HTTPException(422, "duplicate_materialization_target")
        seen.add(identity)
        parsed = {"parameter": parameter, "node_key": node_key, "field": field}
        if "operation" in target:
            parsed["operation"] = operation
        result.append(parsed)
    return result


def build_candidate_graph(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]], configuration: AssistantConfigurationV1,
    targets: list[dict[str, str]], source_nodes: list[dict[str, Any]] | None = None,
    calendar_connection_reference: str | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Validate all destinations, then mutate only a deep in-memory copy."""
    candidate_nodes, candidate_edges = copy.deepcopy(nodes), copy.deepcopy(edges)
    keyed: dict[str, list[dict[str, Any]]] = {}
    for node in candidate_nodes:
        data = node.get("data") if isinstance(node, dict) and isinstance(node.get("data"), dict) else {}
        key = data.get("template_node_key")
        if isinstance(key, str):
            keyed.setdefault(key, []).append(node)
    if any(len(matches) != 1 for matches in keyed.values()):
        raise HTTPException(422, "duplicate_template_node_key")
    source_keyed: dict[str, list[dict[str, Any]]] = {}
    for node in source_nodes if source_nodes is not None else candidate_nodes:
        data = node.get("data") if isinstance(node, dict) and isinstance(node.get("data"), dict) else {}
        key = data.get("template_node_key")
        if isinstance(key, str):
            source_keyed.setdefault(key, []).append(node)
    if any(len(matches) != 1 for matches in source_keyed.values()):
        raise HTTPException(422, "duplicate_template_node_key")
    resolved: list[tuple[dict[str, Any], dict[str, Any], dict[str, str]]] = []
    for target in targets:
        matches = keyed.get(target["node_key"], [])
        source_matches = source_keyed.get(target["node_key"], [])
        if len(matches) != 1 or len(source_matches) != 1:
            raise HTTPException(422, "materialization_target_not_found")
        resolved.append((matches[0], source_matches[0], target))

    values = {
        "clinic_name": configuration.clinic_name,
        # duration_minutes deliberately remains solely in canonical configuration.
        "google_calendar_connection_id": calendar_connection_reference or f"integration:{configuration.google_calendar_connection_id}",
        # enabled is intentionally not represented: V1 never removes graph structure.
        "handoff.reason": configuration.handoff.reason,
    }
    changed: set[str] = set()
    for node, source_node, target in resolved:
        field_name = target["field"].split(".", 1)[1]
        data = node["data"]
        value = (
            _materialized_services(configuration, source_node)
            if target["parameter"] == "services"
            else copy.deepcopy(values[target["parameter"]])
        )
        if target.get("operation", DEFAULT_OPERATION) == "interpolate":
            source_data = source_node.get("data") if isinstance(source_node.get("data"), dict) else {}
            source_value = source_data.get(field_name)
            placeholder = "{{" + target["parameter"] + "}}"
            if not isinstance(source_value, str) or placeholder not in source_value:
                raise HTTPException(422, "materialization_placeholder_missing")
            value = source_value.replace(placeholder, value)
        if data.get(field_name) != value:
            data[field_name] = value
            changed.add(target["parameter"])
    return candidate_nodes, candidate_edges, sorted(changed)


def materialize_configuration(
    db: Session, *, installation_id: UUID, tenant_id: UUID, actor_id: UUID,
    payload: AssistantMaterializationRequest, request: Request | None, commit: bool = True,
) -> dict[str, Any]:
    """Run locks, validation, version creation, baseline and audit atomically."""
    try:
        installation = get_installation_for_configuration(db, installation_id, tenant_id, lock=True)
        configuration_row = db.scalar(select(MarketplaceInstallationAssistantConfiguration).where(
            MarketplaceInstallationAssistantConfiguration.installation_id == installation.id,
        ).with_for_update())
        if configuration_row is None:
            raise HTTPException(422, "assistant_configuration_required")
        if configuration_row.configuration_version != payload.expected_configuration_version:
            raise HTTPException(409, {"code": "assistant_configuration_version_conflict", "current_configuration_version": configuration_row.configuration_version})

        state = assert_managed_flow_baseline(
            db, installation=installation, tenant_id=tenant_id,
            expected_managed_flow_version_id=payload.expected_managed_flow_version_id,
        )
        flow = db.scalar(select(Flow).where(Flow.id == state.flow_id, Flow.tenant_id == tenant_id).with_for_update())
        management = db.scalar(select(MarketplaceInstallationFlowManagement).where(
            MarketplaceInstallationFlowManagement.installation_id == installation.id,
        ).with_for_update())
        resource = next((r for r in installation.resources if r.resource_type == "flow"), None)
        metadata = resource.metadata_json if resource and isinstance(resource.metadata_json, dict) else {}
        version_id = _uuid(metadata.get("template_version_id"))
        template_version = db.scalar(select(MarketplaceTemplateVersion).where(MarketplaceTemplateVersion.id == version_id)) if version_id else None
        if not flow or not management or not template_version or template_version.version != installation.template_version:
            raise HTTPException(422, "invalid_template_provenance")

        configuration = AssistantConfigurationV1.model_validate(configuration_row.configuration)
        binding = db.scalar(select(AssistantCalendarBinding).where(
            AssistantCalendarBinding.installation_id == installation.id,
            AssistantCalendarBinding.tenant_id == tenant_id,
        ))
        if binding is None:
            # Backward-compatible read path for configurations persisted before
            # assistant calendar bindings existed.
            if configuration.effective_calendar_provider != "google_calendar":
                raise HTTPException(422, "assistant_calendar_binding_required")
            connection = db.scalar(select(IntegrationConnection).where(
                IntegrationConnection.id == configuration.google_calendar_connection_id,
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.provider == "google_calendar",
                IntegrationConnection.status == "active",
            ))
            if connection is None:
                raise HTTPException(422, "invalid_google_calendar_connection")
            calendar_reference = f"integration:{configuration.google_calendar_connection_id}"
        else:
            if binding.provider != configuration.effective_calendar_provider:
                raise HTTPException(422, "assistant_calendar_binding_invalid")
            if not binding_is_valid(db, binding):
                raise HTTPException(422, "assistant_calendar_binding_invalid")
            calendar_reference = f"assistant_calendar:{binding.id}"

        current = flow.current_version
        if current is None or current.id != state.current_flow_version_id:
            raise HTTPException(409, "managed_flow_version_conflict")
        nodes, edges = flow_version_nodes_edges(current)
        initial_validation = validate_flow_graph(nodes, edges, mode="draft")
        if not initial_validation["valid"]:
            raise HTTPException(422, "current_flow_invalid")
        candidate_nodes, candidate_edges, changed = build_candidate_graph(
            nodes, edges, configuration, _contract(template_version),
            source_nodes=template_version.nodes_snapshot,
            calendar_connection_reference=calendar_reference,
        )
        candidate_validation = validate_flow_graph(candidate_nodes, candidate_edges, mode="draft")
        if not candidate_validation["valid"]:
            raise HTTPException(422, "materialized_flow_invalid")
        checksum = graph_hash(candidate_nodes, candidate_edges)
        if checksum == current.graph_checksum:
            if commit:
                db.commit()
            else:
                db.flush()
            return _response(installation.id, flow, configuration_row.configuration_version, False, current.id, state.public_dict())

        published_id, active = flow.published_version_id, flow.is_active
        new_version = FlowService(db).create_version(flow, tenant_id, candidate_nodes, candidate_edges)
        # Materialization edits the draft only. These invariants must never move.
        flow.published_version_id, flow.is_active = published_id, active
        management.management_mode = "managed"
        management.managed_flow_version_id = new_version.id
        management.managed_graph_checksum = new_version.graph_checksum
        management.updated_at = datetime.utcnow()
        write_audit_log(
            db, action="assistant_configuration_materialized", tenant_id=tenant_id, user_id=actor_id,
            entity_type="marketplace_installation_flow_management", entity_id=installation.id,
            metadata={
                "installation_id": installation.id, "flow_id": flow.id,
                "template_id": template_version.template_id, "template_version_id": template_version.id,
                "configuration_version": configuration_row.configuration_version,
                "previous_flow_version_id": current.id, "new_flow_version_id": new_version.id,
                "changed_parameters": changed,
            }, request=request,
        )
        if commit:
            db.commit()
        else:
            db.flush()
        public = {"mode": "managed", "flow_id": flow.id, "managed_flow_version_id": new_version.id,
                  "current_flow_version_id": new_version.id, "has_drift": False}
        return _response(installation.id, flow, configuration_row.configuration_version, True, new_version.id, public)
    except Exception:
        db.rollback()
        raise


def _response(installation_id, flow, configuration_version, materialized, version_id, management):
    return {"installation_id": installation_id, "flow_id": flow.id,
            "configuration_version": configuration_version, "materialized": materialized,
            "reason": "materialized" if materialized else "already_up_to_date",
            "flow_version_id": version_id, "management": management}
