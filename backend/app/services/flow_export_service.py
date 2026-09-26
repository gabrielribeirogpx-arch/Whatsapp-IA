from __future__ import annotations

import copy
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any


EXPORT_FORMAT = "wazza_flow"
EXPORT_SCHEMA_VERSION = 1

# These are credential-bearing fields used by integrations in this codebase.  This is
# deliberately an exact-key allow/deny decision: legitimate contract fields such as
# ``max_tokens`` and ``idempotency_key`` must survive the export.
SECRET_KEYS = frozenset(
    {
        "access_token",
        "refresh_token",
        "api_key",
        "x_api_key",
        "apikey",
        "client_secret",
        "webhook_secret",
        "password",
        "secret",
        "token",
        "credential",
        "credentials",
        "authorization",
        "cookie",
    }
)
TENANT_BOUND_REFERENCE_KEYS = frozenset(
    {"connection_id", "integration_id", "provider_id", "phone_number_id", "server_id"}
)
INTEGRATION_PLACEHOLDER = "{{integration.configure_on_import}}"


class FlowExportError(ValueError):
    """The persisted builder graph cannot be represented by the export contract."""


def _sanitize(value: Any, key: str | None = None) -> Any:
    normalized_key = str(key or "").strip().lower().replace("-", "_")
    if normalized_key in SECRET_KEYS:
        return None
    if normalized_key in TENANT_BOUND_REFERENCE_KEYS and value not in (None, ""):
        return INTEGRATION_PLACEHOLDER
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for child_key, child_value in value.items():
            child_normalized = str(child_key).strip().lower().replace("-", "_")
            if child_normalized in SECRET_KEYS:
                continue
            sanitized[str(child_key)] = _sanitize(child_value, str(child_key))
        return sanitized
    if isinstance(value, list):
        return [_sanitize(item, key) for item in value]
    return copy.deepcopy(value)


def sanitize_flow_definition(value: Any) -> Any:
    """Return a detached, secret-free copy without mutating persisted JSON."""

    return _sanitize(value)


def _graph_warnings(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[dict[str, Any]]:
    node_ids = {str(node.get("id")) for node in nodes if isinstance(node, dict) and node.get("id") is not None}
    warnings: list[dict[str, Any]] = []
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            warnings.append({"code": "invalid_edge", "edge_index": index})
            continue
        for endpoint in ("source", "target"):
            value = edge.get(endpoint)
            if value is None or str(value) not in node_ids:
                warnings.append(
                    {
                        "code": "missing_edge_endpoint",
                        "edge_index": index,
                        "endpoint": endpoint,
                        "node_id": str(value) if value is not None else None,
                    }
                )
    return warnings


def build_flow_export(
    flow: Any,
    *,
    nodes: Any,
    edges: Any,
    exported_at: datetime | None = None,
) -> dict[str, Any]:
    """Build the portable read-only contract from the current editor definition.

    Draft graph issues are reported rather than rejected, so an incomplete draft can
    still be downloaded for diagnosis without invoking activation validation.
    """

    if not isinstance(nodes, list):
        raise FlowExportError("nodes must be an array")
    if not isinstance(edges, list):
        raise FlowExportError("edges must be an array")
    if any(not isinstance(node, dict) for node in nodes):
        raise FlowExportError("every node must be an object")

    safe_nodes = sanitize_flow_definition(nodes)
    safe_edges = sanitize_flow_definition(edges)
    warnings = _graph_warnings(safe_nodes, safe_edges)
    timestamp = exported_at or datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)

    return {
        "format": EXPORT_FORMAT,
        "schema_version": EXPORT_SCHEMA_VERSION,
        "exported_at": timestamp.isoformat().replace("+00:00", "Z"),
        "flow": {
            "name": str(getattr(flow, "name", "") or ""),
            "description": getattr(flow, "description", None),
            "runtime_version": getattr(flow, "runtime", None),
            "status": getattr(flow, "status", None),
            "nodes": safe_nodes,
            "edges": safe_edges,
            # The builder currently has no independent persisted variable registry;
            # declarations and references remain losslessly embedded in node data.
            "variables": [],
            "settings": {
                "trigger_type": getattr(flow, "trigger_type", None),
                "trigger_value": getattr(flow, "trigger_value", None),
                "keywords": getattr(flow, "keywords", None),
                "stop_words": getattr(flow, "stop_words", None),
                "priority": getattr(flow, "priority", 0),
            },
            "metadata": {
                "source_version": getattr(flow, "version", None),
                "is_active": bool(getattr(flow, "is_active", False)),
            },
        },
        "validation": {"valid_references": not warnings, "warnings": warnings},
    }


def safe_export_filename(name: str | None) -> str:
    ascii_name = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_name).strip("-").lower()[:80]
    return f"{slug or 'fluxo'}.wazza-flow.json"
