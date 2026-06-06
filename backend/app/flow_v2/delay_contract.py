from __future__ import annotations

import copy
import logging
from typing import Any

logger = logging.getLogger(__name__)

DELAY_LEGACY_DATA_FIELDS = ("content", "delay", "wait_seconds", "duration")
DELAY_LEGACY_NODE_FIELDS = ("delay_seconds", "wait_seconds", "duration", "value", "delay")


def normalize_delay_node(node: dict[str, Any]) -> dict[str, Any]:
    """Return a delay node using the official Runtime V2 contract.

    Official delay contract: ``{"type": "delay", "seconds": 5}``.  Builder and
    legacy snapshots may still contain the delay amount under data.content,
    data.delay, data.wait_seconds or data.duration; these are promoted to the
    top-level ``seconds`` field before validation/runtime execution.
    """

    if not isinstance(node, dict):
        return node
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    node_type = str(node.get("type") or data.get("type") or "message").lower()
    if node_type != "delay":
        return node

    normalized = copy.deepcopy(node)
    normalized_data = normalized.get("data") if isinstance(normalized.get("data"), dict) else {}
    seconds = _coerce_seconds(_first_present(normalized, normalized_data))
    if seconds is not None:
        normalized["seconds"] = seconds

    logger.info(
        "[DELAY NORMALIZED] node_id=%s seconds=%s data=%s",
        normalized.get("id"),
        normalized.get("seconds"),
        normalized_data,
    )

    for key in DELAY_LEGACY_NODE_FIELDS:
        normalized.pop(key, None)
    for key in (*DELAY_LEGACY_DATA_FIELDS, "seconds"):
        normalized_data.pop(key, None)
    if normalized_data:
        normalized["data"] = normalized_data
    else:
        normalized.pop("data", None)
    normalized["type"] = "delay"
    return normalized


def normalize_delay_nodes(nodes: list[dict[str, Any]] | tuple[dict[str, Any], ...] | None) -> list[dict[str, Any]]:
    return [normalize_delay_node(node) if isinstance(node, dict) else node for node in (nodes or [])]


def _first_present(node: dict[str, Any], data: dict[str, Any]) -> Any:
    for getter in (
        lambda: node.get("seconds"),
        lambda: data.get("seconds"),
        lambda: data.get("content"),
        lambda: data.get("delay"),
        lambda: data.get("wait_seconds"),
        lambda: data.get("duration"),
        lambda: node.get("delay_seconds"),
        lambda: node.get("wait_seconds"),
        lambda: node.get("duration"),
        lambda: node.get("value"),
        lambda: node.get("delay"),
    ):
        value = getter()
        if value not in (None, ""):
            return value
    return None


def _coerce_seconds(value: Any) -> int | float | None:
    if value in (None, ""):
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return value
    return int(numeric) if numeric.is_integer() else numeric
