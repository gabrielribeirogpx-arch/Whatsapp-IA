from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
import re
from urllib.parse import urlparse
import ipaddress


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


SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_.]+$")

NODE_TOOL_ALLOWED_TYPES = {"ai_classification", "ai_extraction", "ai_summary", "ai_response", "action", "condition", "message"}
NODE_TOOL_ID_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


class FlowV2GraphValidator:
    """Validates Flow Publisher V2 graphs before immutable snapshot creation."""

    SUPPORTED_NODE_TYPES = {"message", "choice", "condition", "delay", "action", "media", "cta_url", "ai_rag", "ai_response", "ai_classification", "ai_extraction", "ai_summary", "ai_agent", "ai_supervisor", "start"}
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
        self._validate_ai_answer_edges(nodes_payload, edges_payload, errors)
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
            self._validate_node_config(node_id_str, node, errors, nodes=nodes)
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


    def _validate_ai_answer_edges(
        self,
        nodes: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        errors: list[str],
    ) -> None:
        outgoing_sources = {str(self._edge_source(edge)) for edge in edges if isinstance(edge, dict) and self._edge_source(edge) not in (None, "")}
        for node in nodes:
            if not isinstance(node, dict) or node.get("id") in (None, "") or self._node_type(node) not in {"ai_rag", "ai_response", "ai_agent", "ai_supervisor"}:
                continue
            node_id = str(node["id"])
            node_type = self._node_type(node).upper()
            data = self._node_data(node)
            behavior = str(
                data.get("after_agent_behavior")
                or data.get("afterAgentBehavior")
                or data.get("after_answer_behavior")
                or data.get("afterAnswerBehavior")
                or "end_flow"
            ).strip().lower()
            if behavior not in {"end_flow", "continue_to_next", "wait_same_node"}:
                errors.append(f"FLOW_V2_{node_type}_AFTER_ANSWER_BEHAVIOR_INVALID:{node_id}")
                continue
            if behavior == "continue_to_next" and node_id not in outgoing_sources:
                errors.append(f"FLOW_V2_{node_type}_CONTINUE_TO_NEXT_REQUIRES_EDGE:{node_id}")

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
        self, node_id: str, node: dict[str, Any], errors: list[str], *, nodes: list[dict[str, Any]] | None = None
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
            if media_type not in {"image", "document", "audio", "video"}:
                errors.append(f"FLOW_V2_MEDIA_TYPE_INVALID:{node_id}")
            if not media_url or (not media_url.startswith("https://") and "{{" not in media_url):
                errors.append(f"FLOW_V2_MEDIA_URL_INVALID:{node_id}")
        elif node_type == "cta_url":
            text = str(node.get("text") or node.get("content") or data.get("text") or data.get("content") or data.get("message") or "").strip()
            button_text = str(node.get("button_text") or data.get("button_text") or data.get("buttonText") or data.get("button") or "").strip()
            url = str(node.get("url") or data.get("url") or data.get("href") or "").strip()
            if not text:
                errors.append(f"FLOW_V2_CTA_URL_TEXT_REQUIRED:{node_id}")
            if not button_text:
                errors.append(f"FLOW_V2_CTA_URL_BUTTON_TEXT_REQUIRED:{node_id}")
            elif len(button_text) > 20:
                errors.append(f"FLOW_V2_CTA_URL_BUTTON_TEXT_TOO_LONG:{node_id}")
            if not url.startswith("https://") and "{{" not in url:
                errors.append(f"FLOW_V2_CTA_URL_HTTPS_REQUIRED:{node_id}")
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
        elif node_type in {"ai_rag", "ai_response"}:
            if self._contains_forbidden_secret(data):
                errors.append(f"FLOW_V2_AI_NODE_API_KEY_FORBIDDEN:{node_id}")
        elif node_type == "ai_agent":
            if self._contains_forbidden_secret(data):
                errors.append(f"FLOW_V2_AI_NODE_API_KEY_FORBIDDEN:{node_id}")
            allowed_tools = data.get("allowed_tools") or data.get("allowedTools") or []
            if not isinstance(allowed_tools, list) or not [t for t in allowed_tools if str(t).strip()]:
                errors.append(f"FLOW_V2_AI_AGENT_ALLOWED_TOOLS_REQUIRED:{node_id}")
            max_steps = data.get("max_steps", data.get("maxSteps", 3))
            try:
                if int(max_steps) < 1 or int(max_steps) > 5:
                    errors.append(f"FLOW_V2_AI_AGENT_MAX_STEPS_INVALID:{node_id}")
            except (TypeError, ValueError):
                errors.append(f"FLOW_V2_AI_AGENT_MAX_STEPS_INVALID:{node_id}")
            node_tools = data.get("node_tools") or data.get("nodeTools") or []
            if data.get("allow_node_tools", data.get("allowNodeTools", False)) is True:
                if not isinstance(node_tools, list):
                    errors.append(f"FLOW_V2_AI_AGENT_NODE_TOOLS_INVALID:{node_id}")
                else:
                    node_by_id = {str(n.get("id")): n for n in (nodes or []) if isinstance(n, dict)}
                    for index, tool in enumerate(node_tools):
                        if not isinstance(tool, dict):
                            errors.append(f"FLOW_V2_AI_AGENT_NODE_TOOL_INVALID:{node_id}:{index}")
                            continue
                        tool_id = str(tool.get("tool_id") or "")
                        target_id = str(tool.get("node_id") or "")
                        if not NODE_TOOL_ID_RE.match(tool_id):
                            errors.append(f"FLOW_V2_AI_AGENT_NODE_TOOL_ID_INVALID:{node_id}:{index}")
                        if len(str(tool.get("label") or "")) > 80 or len(str(tool.get("description") or "")) > 500:
                            errors.append(f"FLOW_V2_AI_AGENT_NODE_TOOL_TEXT_TOO_LONG:{node_id}:{index}")
                        target = node_by_id.get(target_id)
                        target_type = self._node_type(target) if isinstance(target, dict) else ""
                        if not target or target_id == str(node_id) or target_type == "ai_agent" or target_type not in NODE_TOOL_ALLOWED_TYPES:
                            errors.append(f"FLOW_V2_AI_AGENT_NODE_TOOL_TARGET_INVALID:{node_id}:{index}")
                        if self._contains_forbidden_secret(tool):
                            errors.append(f"FLOW_V2_AI_AGENT_NODE_TOOL_SECRET_FORBIDDEN:{node_id}:{index}")
                try:
                    calls = int(data.get("max_node_tool_calls", data.get("maxNodeToolCalls", 3)))
                    if calls < 1 or calls > 5:
                        errors.append(f"FLOW_V2_AI_AGENT_MAX_NODE_TOOL_CALLS_INVALID:{node_id}")
                except (TypeError, ValueError):
                    errors.append(f"FLOW_V2_AI_AGENT_MAX_NODE_TOOL_CALLS_INVALID:{node_id}")
            subflow_tools = data.get("subflow_tools") or data.get("subflowTools") or []
            if data.get("allow_subflow_tools", data.get("allowSubflowTools", False)) is True:
                if not isinstance(subflow_tools, list) or not subflow_tools:
                    errors.append(f"FLOW_V2_AI_AGENT_SUBFLOW_TOOLS_REQUIRED:{node_id}")
                else:
                    for index, tool in enumerate(subflow_tools):
                        if not isinstance(tool, dict):
                            errors.append(f"FLOW_V2_AI_AGENT_SUBFLOW_TOOL_INVALID:{node_id}:{index}")
                            continue
                        tool_id = str(tool.get("tool_id") or "")
                        if not NODE_TOOL_ID_RE.match(tool_id):
                            errors.append(f"FLOW_V2_AI_AGENT_SUBFLOW_TOOL_ID_INVALID:{node_id}:{index}")
                        if len(str(tool.get("label") or "")) > 80 or len(str(tool.get("description") or "")) > 300:
                            errors.append(f"FLOW_V2_AI_AGENT_SUBFLOW_TOOL_TEXT_TOO_LONG:{node_id}:{index}")
                        flow_ref = str(tool.get("flow_id") or tool.get("flowId") or "").strip()
                        if not flow_ref or flow_ref == str(data.get("flow_id") or data.get("flowId") or ""):
                            errors.append(f"FLOW_V2_AI_AGENT_SUBFLOW_FLOW_INVALID:{node_id}:{index}")
                        for var_key in ("input_variable", "inputVariable", "output_variable", "outputVariable"):
                            if tool.get(var_key) and not SAFE_NAME_RE.match(str(tool.get(var_key))):
                                errors.append(f"FLOW_V2_AI_AGENT_SUBFLOW_VARIABLE_INVALID:{node_id}:{index}")
                        try:
                            timeout = int(tool.get("timeout_seconds", tool.get("timeoutSeconds", 20)))
                            if timeout < 3 or timeout > 60:
                                errors.append(f"FLOW_V2_AI_AGENT_SUBFLOW_TIMEOUT_INVALID:{node_id}:{index}")
                        except (TypeError, ValueError):
                            errors.append(f"FLOW_V2_AI_AGENT_SUBFLOW_TIMEOUT_INVALID:{node_id}:{index}")
                        if self._contains_forbidden_secret(tool):
                            errors.append(f"FLOW_V2_AI_AGENT_SUBFLOW_SECRET_FORBIDDEN:{node_id}:{index}")
                try:
                    calls = int(data.get("max_subflow_calls", data.get("maxSubflowCalls", 2)))
                    if calls < 1 or calls > 3:
                        errors.append(f"FLOW_V2_AI_AGENT_MAX_SUBFLOW_CALLS_INVALID:{node_id}")
                except (TypeError, ValueError):
                    errors.append(f"FLOW_V2_AI_AGENT_MAX_SUBFLOW_CALLS_INVALID:{node_id}")
            if isinstance(allowed_tools, list) and "chamar_webhook" in [str(t) for t in allowed_tools]:
                webhooks = data.get("webhooks") or []
                if not isinstance(webhooks, list) or not webhooks:
                    errors.append(f"FLOW_V2_AI_AGENT_WEBHOOKS_REQUIRED:{node_id}")
                else:
                    for index, webhook in enumerate(webhooks):
                        url = str(webhook.get("url") if isinstance(webhook, dict) else "")
                        method = str(webhook.get("method", "POST") if isinstance(webhook, dict) else "POST").upper()
                        if method not in {"GET", "POST"}:
                            errors.append(f"FLOW_V2_AI_AGENT_WEBHOOK_METHOD_INVALID:{node_id}:{index}")
                        if self._is_internal_url(url):
                            errors.append(f"FLOW_V2_AI_AGENT_WEBHOOK_URL_INVALID:{node_id}:{index}")
        elif node_type == "ai_supervisor":
            if self._contains_forbidden_secret(data):
                errors.append(f"FLOW_V2_AI_NODE_API_KEY_FORBIDDEN:{node_id}")
            agent_ids = data.get("agent_ids") or data.get("agentIds") or data.get("agents") or []
            if not isinstance(agent_ids, list) or not [item for item in agent_ids if str(item).strip()]:
                errors.append(f"FLOW_V2_AI_SUPERVISOR_AGENTS_REQUIRED:{node_id}")
                return
            node_by_id = {str(n.get("id")): n for n in (nodes or []) if isinstance(n, dict) and n.get("id") not in (None, "")}
            for index, raw_target_id in enumerate(agent_ids):
                target_id = str(raw_target_id)
                target = node_by_id.get(target_id)
                target_type = self._node_type(target) if isinstance(target, dict) else ""
                if target_id == node_id:
                    errors.append(f"FLOW_V2_AI_SUPERVISOR_SELF_TARGET_INVALID:{node_id}:{index}")
                if target_type == "ai_supervisor":
                    errors.append(f"FLOW_V2_AI_SUPERVISOR_TARGET_SUPERVISOR_INVALID:{node_id}:{index}")
                if target_type != "ai_agent":
                    errors.append(f"FLOW_V2_AI_SUPERVISOR_TARGET_INVALID:{node_id}:{index}")
            fallback_id = str(data.get("fallback_agent_id") or data.get("fallbackAgentId") or "").strip()
            if fallback_id and fallback_id not in {str(item) for item in agent_ids}:
                errors.append(f"FLOW_V2_AI_SUPERVISOR_FALLBACK_INVALID:{node_id}")
            try:
                max_agents = int(data.get("max_agents", data.get("maxAgents", 1)))
                if max_agents != 1:
                    errors.append(f"FLOW_V2_AI_SUPERVISOR_MAX_AGENTS_INVALID:{node_id}")
            except (TypeError, ValueError):
                errors.append(f"FLOW_V2_AI_SUPERVISOR_MAX_AGENTS_INVALID:{node_id}")
        elif node_type == "ai_classification":
            if any(str(data.get(key) or "").strip() for key in ("api_key", "apiKey", "openai_api_key", "provider_api_key")):
                errors.append(f"FLOW_V2_AI_NODE_API_KEY_FORBIDDEN:{node_id}")
            categories = data.get("categories")
            if not isinstance(categories, list) or len([c for c in categories if str(c).strip()]) < 2:
                errors.append(f"FLOW_V2_AI_CLASSIFICATION_CATEGORIES_INVALID:{node_id}")
            output_variable = str(data.get("output_variable") or data.get("outputVariable") or "ai.classification")
            if not SAFE_NAME_RE.match(output_variable):
                errors.append(f"FLOW_V2_AI_OUTPUT_VARIABLE_INVALID:{node_id}")
        elif node_type == "ai_extraction":
            if any(str(data.get(key) or "").strip() for key in ("api_key", "apiKey", "openai_api_key", "provider_api_key")):
                errors.append(f"FLOW_V2_AI_NODE_API_KEY_FORBIDDEN:{node_id}")
            fields = data.get("fields")
            if not isinstance(fields, list) or not fields:
                errors.append(f"FLOW_V2_AI_EXTRACTION_FIELDS_INVALID:{node_id}")
            else:
                for index, field in enumerate(fields):
                    name = str(field.get("name") if isinstance(field, dict) else "")
                    if not SAFE_NAME_RE.match(name):
                        errors.append(f"FLOW_V2_AI_EXTRACTION_FIELD_NAME_INVALID:{node_id}:{index}")
            output_variable = str(data.get("output_variable") or data.get("outputVariable") or "ai.extraction")
            if not SAFE_NAME_RE.match(output_variable):
                errors.append(f"FLOW_V2_AI_OUTPUT_VARIABLE_INVALID:{node_id}")
        elif node_type == "ai_summary":
            if any(str(data.get(key) or "").strip() for key in ("api_key", "apiKey", "openai_api_key", "provider_api_key")):
                errors.append(f"FLOW_V2_AI_NODE_API_KEY_FORBIDDEN:{node_id}")
            summary_source = str(data.get("summary_source") or data.get("summarySource") or "conversation_history").strip().lower()
            if summary_source not in {"conversation_history", "custom_text"}:
                errors.append(f"FLOW_V2_AI_SUMMARY_SOURCE_INVALID:{node_id}")
            if summary_source == "custom_text" and not str(data.get("input_template") or data.get("inputTemplate") or "").strip():
                errors.append(f"FLOW_V2_AI_SUMMARY_INPUT_TEMPLATE_REQUIRED:{node_id}")
            summary_format = str(data.get("summary_format") or data.get("summaryFormat") or "handoff").strip().lower()
            if summary_format not in {"short", "detailed", "bullet_points", "handoff"}:
                errors.append(f"FLOW_V2_AI_SUMMARY_FORMAT_INVALID:{node_id}")
            output_variable = str(data.get("output_variable") or data.get("outputVariable") or "ai.summary")
            if not SAFE_NAME_RE.match(output_variable):
                errors.append(f"FLOW_V2_AI_OUTPUT_VARIABLE_INVALID:{node_id}")

    def _contains_forbidden_secret(self, value: Any) -> bool:
        """Return True when a graph payload embeds credential material.

        Uses precise credential field names instead of broad substring matching
        so safe runtime fields such as ``max_tokens`` and MCP tool references
        are not interpreted as API keys.
        """
        if isinstance(value, dict):
            for key, item in value.items():
                if self._is_forbidden_secret_key(key) and str(item or "").strip():
                    return True
                if self._contains_forbidden_secret(item):
                    return True
        elif isinstance(value, list):
            return any(self._contains_forbidden_secret(item) for item in value)
        return False

    @staticmethod
    def _is_forbidden_secret_key(key: Any) -> bool:
        normalized = re.sub(r"[^a-z0-9]", "_", str(key).strip().lower()).strip("_")
        if not normalized:
            return False
        forbidden_exact = {
            "api_key",
            "apikey",
            "openai_api_key",
            "provider_api_key",
            "secret",
            "client_secret",
            "password",
            "credential",
            "credentials",
            "headers",
            "authorization",
            "cookie",
            "token",
            "access_token",
            "refresh_token",
            "auth_token",
            "bearer_token",
        }
        if normalized in forbidden_exact:
            return True
        return (
            normalized.endswith("_api_key")
            or normalized.endswith("_secret")
            or normalized.endswith("_token")
        )

    def _is_internal_url(self, url: str) -> bool:
        parsed = urlparse(str(url or ""))
        if parsed.scheme != "https" or not parsed.hostname:
            return True
        host = parsed.hostname.lower()
        if host in {"localhost", "0.0.0.0"} or host.endswith(".localhost"):
            return True
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            return False
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_unspecified

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

    @classmethod
    def _is_terminal_node(cls, node: dict[str, Any]) -> bool:
        data = cls._node_data(node)
        return bool(node.get("is_terminal") or node.get("isTerminal") or node.get("endFlow") or data.get("is_terminal") or data.get("isTerminal") or data.get("endFlow"))

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
