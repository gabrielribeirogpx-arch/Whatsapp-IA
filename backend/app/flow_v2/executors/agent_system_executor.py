"""Specialized agent-system template executors."""
from __future__ import annotations

import logging
from typing import Any

from app.flow_v2.actions import SendMessageAction
from app.flow_v2.executors._legacy import (
    AiCalendarAgentNodeExecutor,
    AiDispatcherNodeExecutor,
    AiGreetingNodeExecutor,
    AiSafeFallbackNodeExecutor,
    BaseNodeExecutor,
    FlowV2EventType,
    NodeExecutionResult,
)

logger = logging.getLogger(__name__)


def _first_present_mapping(*values: Any) -> dict[str, Any]:
    for value in values:
        if isinstance(value, dict):
            return value
    return {}


def _first_present_list(*values: Any) -> list[Any]:
    for value in values:
        if isinstance(value, list):
            return value
    return []


class AiSystemNodeExecutor(BaseNodeExecutor):
    """Executor for the composed AI System / Agenda Inteligente node.

    The node is intentionally self-contained: it can run when the published
    snapshot contains only the composed node and no top-level Runtime V2 edges.
    """

    CALENDAR_SYSTEM_TYPES = {"ai_calendar_agent_system", "intelligent_calendar"}
    CALENDAR_GREETING = "Olá! Posso te ajudar a consultar disponibilidade, agendar ou cancelar um evento."

    def execute(self, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        system_type = str(
            data.get("system_type")
            or data.get("systemType")
            or data.get("agent_system_template_id")
            or "ai_system"
        ).strip()
        input_text = str(getattr(runtime_input, "message_text", None) or runtime_input.metadata.get("message_text") or "").strip()
        internal_nodes = _first_present_list(data.get("internal_nodes"), data.get("internalNodes"), data.get("nodes"))
        internal_edges = _first_present_list(data.get("internal_edges"), data.get("internalEdges"), data.get("edges"))
        tools = _first_present_list(data.get("tools"), data.get("tool_ids"), data.get("toolIds"), data.get("mcp_tool_ids"), data.get("mcpToolIds"))
        integrations = _first_present_mapping(data.get("integrations"), data.get("integration_config"), data.get("integrationConfig"))

        logger.info(
            "event=AI_SYSTEM_EXECUTOR_START node_id=%s system_type=%s internal_nodes_count=%s internal_edges_count=%s tools_count=%s integrations_count=%s",
            node_id, system_type, len(internal_nodes), len(internal_edges), len(tools), len(integrations),
        )
        logger.info("event=AI_SYSTEM_EXECUTOR_INPUT node_id=%s text=%s", node_id, input_text[:500])

        try:
            normalized_system_type = system_type.lower()
            response_text = self.CALENDAR_GREETING
            tool_decision = "none"
            if normalized_system_type in self.CALENDAR_SYSTEM_TYPES:
                tool_decision = self._calendar_tool_decision(input_text)
                logger.info(
                    "event=AI_SYSTEM_EXECUTOR_TOOL_DECISION node_id=%s system_type=%s decision=%s tools=%s",
                    node_id, system_type, tool_decision, tools,
                )
            logger.info("event=AI_SYSTEM_EXECUTOR_RESPONSE node_id=%s response=%s", node_id, response_text[:500])
            self.event_store.append(
                db,
                session=session,
                event_type=FlowV2EventType.OUTPUT_EMITTED,
                node_id=node_id,
                payload={
                    "analytics_event": "AI_SYSTEM_EXECUTOR_RESPONSE",
                    "system_type": system_type,
                    "tool_decision": tool_decision,
                    "text": response_text,
                },
            )
            action = SendMessageAction(
                tenant_id=session.tenant_id,
                session_id=session.id,
                external_user_id=runtime_input.external_user_id,
                conversation_id=runtime_input.conversation_id,
                contact_id=runtime_input.contact_id,
                text=response_text,
                metadata={
                    **runtime_input.metadata,
                    "node_id": node_id,
                    "intent": "ai_system",
                    "system_type": system_type,
                    "tool_decision": tool_decision,
                },
            )
            return NodeExecutionResult(actions=(action,), next_node_id=node_id, status="wait")
        except Exception as exc:
            logger.exception("event=AI_SYSTEM_EXECUTOR_ERROR node_id=%s system_type=%s error=%s", node_id, system_type, exc)
            raise

    @staticmethod
    def _calendar_tool_decision(input_text: str) -> str:
        normalized = input_text.casefold()
        if any(term in normalized for term in ("cancel", "desmarc", "excluir", "remover")):
            return "calendar_delete"
        if any(term in normalized for term in ("dispon", "horário", "horario", "livre")):
            return "calendar_list"
        if any(term in normalized for term in ("agenda", "agendar", "marcar", "reunião", "reuniao", "evento")):
            return "calendar_create"
        return "respond"


__all__ = [
    "AiDispatcherNodeExecutor",
    "AiGreetingNodeExecutor",
    "AiCalendarAgentNodeExecutor",
    "AiSafeFallbackNodeExecutor",
    "AiSystemNodeExecutor",
]
