from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class GraphValidationStatus(StrEnum):
    VALID = "VALID"
    INVALID = "INVALID"


@dataclass(frozen=True)
class GraphValidationResult:
    status: GraphValidationStatus
    errors: tuple[str, ...] = ()

    @property
    def is_valid(self) -> bool:
        return self.status == GraphValidationStatus.VALID


class FlowV2GraphValidator:
    """Validates Flow Publisher V2 graphs before immutable snapshot creation."""

    SUPPORTED_NODE_TYPES = {"message", "choice", "condition", "delay", "action", "media", "start"}
    SUPPORTED_CONDITION_OPERATORS = {"==", "eq", "equals"}
    SUPPORTED_BUILDER_MATCH_TYPES = {"contains", "equals", "eq", "=="}

    def validate(
        self, *, nodes: list[dict[str, Any]] | None, edges: list[dict[str, Any]] | None
    ) -> GraphValidationResult:
        errors: list[str] = []
        nodes_payload = nodes if isinstance(nodes, list) else []
        edges_payload = edges if isinstance(edges, list) else []

        node_ids = self._validate_nodes(nodes_payload, errors)
        self._validate_edges(edges_payload, node_ids, errors)
        self._validate_choice_edges(nodes_payload, edges_payload, errors)
        start_node_ids = self._start_node_ids(nodes_payload)
        if len(start_node_ids) != 1:
            errors.append("FLOW_V2_REQUIRES_EXACTLY_ONE_START_NODE")

        if node_ids and len(start_node_ids) == 1:
            self._validate_reachability(
                start_node_ids[0], node_ids, edges_payload, errors
            )

        return GraphValidationResult(
            status=(
                GraphValidationStatus.INVALID if errors else GraphValidationStatus.VALID
            ),
            errors=tuple(errors),
        )

    def _validate_nodes(
        self, nodes: list[dict[str, Any]], errors: list[str]
    ) -> set[str]:
        node_ids: set[str] = set()
        for index, node in enumerate(nodes):
            if not isinstance(node, dict):
                errors.append(f"FLOW_V2_NODE_{index}_INVALID")
                continue
            node_id = node.get("id")
            if node_id in (None, ""):
                errors.append(f"FLOW_V2_NODE_{index}_MISSING_ID")
                continue
            node_id_str = str(node_id)
            if node_id_str in node_ids:
                errors.append(f"FLOW_V2_DUPLICATE_NODE_ID:{node_id_str}")
            node_ids.add(node_id_str)
            node_type = self._node_type(node)
            if node_type not in self.SUPPORTED_NODE_TYPES:
                errors.append(f"FLOW_V2_NODE_TYPE_UNSUPPORTED:{node_id_str}:{node_type}")
            self._validate_node_config(node_id_str, node, errors)
        return node_ids

    def _validate_edges(
        self, edges: list[dict[str, Any]], node_ids: set[str], errors: list[str]
    ) -> None:
        for index, edge in enumerate(edges):
            if not isinstance(edge, dict):
                errors.append(f"FLOW_V2_EDGE_{index}_INVALID")
                continue
            source = self._edge_source(edge)
            target = self._edge_target(edge)
            if source in (None, ""):
                errors.append(f"FLOW_V2_EDGE_{index}_MISSING_SOURCE")
            elif str(source) not in node_ids:
                errors.append(f"FLOW_V2_EDGE_SOURCE_NOT_FOUND:{source}")
            if target in (None, ""):
                errors.append(f"FLOW_V2_EDGE_{index}_MISSING_TARGET")
            elif str(target) not in node_ids:
                errors.append(f"FLOW_V2_EDGE_TARGET_NOT_FOUND:{target}")
            if (
                source not in (None, "")
                and target not in (None, "")
                and (str(source) not in node_ids or str(target) not in node_ids)
            ):
                edge_id = edge.get("id", index)
                errors.append(f"FLOW_V2_BROKEN_EDGE:{edge_id}")

    def _validate_choice_edges(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        errors: list[str],
    ) -> None:
        choice_node_ids = {
            str(node["id"])
            for node in nodes
            if isinstance(node, dict)
            and node.get("id") not in (None, "")
            and self._node_type(node) == "choice"
        }
        if not choice_node_ids:
            return
        for index, edge in enumerate(edges):
            if not isinstance(edge, dict):
                continue
            source = self._edge_source(edge)
            if source in (None, "") or str(source) not in choice_node_ids:
                continue
            source_handle = (
                edge.get("sourceHandle")
                if edge.get("sourceHandle") is not None
                else edge.get("source_handle")
            )
            if source_handle in (None, ""):
                errors.append(f"FLOW_V2_CHOICE_SOURCE_HANDLE_REQUIRED:{source}:{index}")

    def _validate_reachability(
        self,
        start_node_id: str,
        node_ids: set[str],
        edges: list[dict[str, Any]],
        errors: list[str],
    ) -> None:
        adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_ids}
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            source = self._edge_source(edge)
            target = self._edge_target(edge)
            if source in (None, "") or target in (None, ""):
                continue
            source_id = str(source)
            target_id = str(target)
            if source_id in node_ids and target_id in node_ids:
                adjacency[source_id].add(target_id)

        reachable: set[str] = set()
        pending = [start_node_id]
        while pending:
            current = pending.pop()
            if current in reachable:
                continue
            reachable.add(current)
            pending.extend(sorted(adjacency.get(current, set()) - reachable))

        unreachable = sorted(node_ids - reachable)
        for node_id in unreachable:
            errors.append(f"FLOW_V2_UNREACHABLE_NODE:{node_id}")
            errors.append(f"FLOW_V2_ORPHAN_NODE:{node_id}")

    def _validate_node_config(
        self, node_id: str, node: dict[str, Any], errors: list[str]
    ) -> None:
        node_type = self._node_type(node)
        data = self._node_data(node)
        if node_type == "choice":
            display_mode = str(node.get("display_mode") or data.get("display_mode") or data.get("displayMode") or "buttons").strip().lower()
            if display_mode not in {"buttons", "list"}:
                errors.append(f"FLOW_V2_CHOICE_DISPLAY_MODE_INVALID:{node_id}")
            options = node.get("options") or data.get("options") or []
            if not isinstance(options, list) or not options:
                errors.append(f"FLOW_V2_CHOICE_OPTIONS_INVALID:{node_id}")
                return
            for index, option in enumerate(options):
                if not isinstance(option, dict) or option.get("id") in (None, ""):
                    errors.append(
                        f"FLOW_V2_CHOICE_OPTION_ID_REQUIRED:{node_id}:{index}"
                    )
        elif node_type == "delay":
            seconds = node.get("seconds")
            try:
                if float(seconds) <= 0:
                    errors.append(f"FLOW_V2_DELAY_SECONDS_MUST_BE_POSITIVE:{node_id}")
            except (TypeError, ValueError):
                errors.append(f"FLOW_V2_DELAY_SECONDS_MUST_BE_POSITIVE:{node_id}")
        elif node_type == "media":
            media_type = str(node.get("media_type") or data.get("media_type") or "").strip().lower()
            media_url = str(node.get("media_url") or data.get("media_url") or data.get("url") or "").strip()
            if media_type not in {"image", "document"}:
                errors.append(f"FLOW_V2_MEDIA_TYPE_INVALID:{node_id}")
            if not media_url or not media_url.startswith("https://"):
                errors.append(f"FLOW_V2_MEDIA_URL_INVALID:{node_id}")
        elif node_type == "condition":
            conditions = node.get("conditions") or data.get("conditions")
            if self._has_valid_builder_condition(data):
                return
            if not isinstance(conditions, list) or not conditions:
                errors.append(f"FLOW_V2_CONDITION_CONFIG_INVALID:{node_id}")
                return
            for index, condition in enumerate(conditions):
                if not self._is_valid_condition(condition):
                    errors.append(f"FLOW_V2_CONDITION_CONFIG_INVALID:{node_id}:{index}")

    def _has_valid_builder_condition(self, data: dict[str, Any]) -> bool:
        keywords = self._builder_keywords(data)
        match_type = (
            str(data.get("matchType") or data.get("match_type") or "equals")
            .strip()
            .lower()
        )
        return bool(keywords) and match_type in self.SUPPORTED_BUILDER_MATCH_TYPES

    @staticmethod
    def _builder_keywords(data: dict[str, Any]) -> list[str]:
        for key in ("keywords", "positive", "condition"):
            raw_value = data.get(key)
            if isinstance(raw_value, list):
                keywords = [
                    str(item).strip() for item in raw_value if str(item).strip()
                ]
            elif isinstance(raw_value, str):
                keywords = [
                    part.strip()
                    for part in raw_value.replace("\n", ",").split(",")
                    if part.strip()
                ]
            else:
                keywords = []
            if keywords:
                return keywords
        return []

    def _is_valid_condition(self, condition: Any) -> bool:
        if not isinstance(condition, dict):
            return False
        left = condition.get("left") or condition.get("field") or condition.get("path")
        operator = condition.get("operator") or condition.get("op") or "=="
        has_expected = "right" in condition or "value" in condition
        return (
            bool(left)
            and has_expected
            and operator in self.SUPPORTED_CONDITION_OPERATORS
        )

    @classmethod
    def _start_node_ids(cls, nodes: list[dict[str, Any]]) -> list[str]:
        return [
            str(node["id"])
            for node in nodes
            if isinstance(node, dict)
            and node.get("id") not in (None, "")
            and cls._is_start_node(node)
        ]

    @classmethod
    def _is_start_node(cls, node: dict[str, Any]) -> bool:
        data = cls._node_data(node)
        return (
            bool(
                node.get("isStart")
                or node.get("is_start")
                or data.get("isStart")
                or data.get("is_start")
            )
            or cls._node_type(node) == "start"
            or str(node.get("id")) == "start"
        )

    @staticmethod
    def _node_type(node: dict[str, Any]) -> str:
        data = FlowV2GraphValidator._node_data(node)
        return str(node.get("type") or data.get("type") or "message").lower()

    @staticmethod
    def _node_data(node: dict[str, Any]) -> dict[str, Any]:
        data = node.get("data")
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _edge_source(edge: dict[str, Any]) -> Any:
        return edge.get("source") or edge.get("from") or edge.get("source_node_id")

    @staticmethod
    def _edge_target(edge: dict[str, Any]) -> Any:
        return edge.get("target") or edge.get("to") or edge.get("target_node_id")
