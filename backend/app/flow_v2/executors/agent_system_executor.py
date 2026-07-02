"""Specialized agent-system template executors."""
from __future__ import annotations

import logging
import traceback
from typing import Any

from app.tools.context import sanitize_metadata

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
from app.flow_v2.snapshot import FlowV2Snapshot, build_transitions_from_edges, canonical_hash

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


class _InternalRuntimeSession:
    """Isolated internal cursor that shares the parent event stream cursor.

    Internal AI System nodes execute against a private current_node_id, but their
    runtime events are still appended to the outer Flow V2 session stream.
    Forwarding last_event_index to the parent prevents internal append calls from
    reusing indexes that the outer executor will append later in the same turn.
    """

    def __init__(self, *, parent: Any, current_node_id: str) -> None:
        self._parent = parent
        self.id = parent.id
        self.tenant_id = parent.tenant_id
        self.flow_version_id = getattr(parent, "flow_version_id", None)
        self.contact_id = getattr(parent, "contact_id", None)
        self.conversation_id = getattr(parent, "conversation_id", None)
        self.external_user_id = getattr(parent, "external_user_id", None)
        self.context = getattr(parent, "context", {})
        self.current_node_id = current_node_id
        self.status = "running"

    @property
    def last_event_index(self) -> int:
        return int(getattr(self._parent, "last_event_index", 0) or 0)

    @last_event_index.setter
    def last_event_index(self, value: int) -> None:
        setattr(self._parent, "last_event_index", value)


class AiSystemNodeExecutor(BaseNodeExecutor):
    """Dispatcher for the private runtime graph stored inside an AI System node."""

    FALLBACK_MESSAGE = "Não consegui iniciar o sistema de IA. Tente novamente em instantes."
    GOOGLE_CALENDAR_CONNECTION_ERROR_MESSAGE = "Não consegui acessar sua conexão com Google Calendar"
    INTERNAL_CONTEXT_KEY = "ai_system_internal_runtime"

    def execute(self, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
        node_id = str(node["id"])
        data = self._node_data(node)
        system_type = str(data.get("system_type") or data.get("systemType") or data.get("agent_system_template_id") or "ai_system").strip()
        internal_nodes = _first_present_list(data.get("internal_nodes"), data.get("internalNodes"), data.get("nodes"))
        internal_edges = _first_present_list(data.get("internal_edges"), data.get("internalEdges"), data.get("edges"))
        logger.info(
            "event=AI_SYSTEM_INTERNAL_RUNTIME_START node_id=%s system_type=%s internal_nodes_count=%s internal_edges_count=%s",
            node_id,
            system_type,
            len(internal_nodes),
            len(internal_edges),
        )
        if not internal_nodes:
            return self._fallback(db, session=session, node_id=node_id, runtime_input=runtime_input, reason="missing_internal_nodes")

        try:
            internal_snapshot = self._build_internal_snapshot(snapshot, node_id=node_id, system_type=system_type, internal_nodes=internal_nodes, internal_edges=internal_edges)
            start_node_id = self._resume_or_start_node_id(session=session, system_node_id=node_id, internal_snapshot=internal_snapshot)
            internal_session = self._internal_session(session=session, current_node_id=start_node_id)
            actions = self._execute_internal_runtime(db, snapshot=internal_snapshot, session=internal_session, runtime_input=runtime_input, system_node_id=node_id)
            self._persist_internal_pointer(session=session, system_node_id=node_id, current_node_id=getattr(internal_session, "current_node_id", None))
            logger.info("event=AI_SYSTEM_INTERNAL_FINISHED node_id=%s current_internal_node_id=%s actions_count=%s", node_id, getattr(internal_session, "current_node_id", None), len(actions))
            return NodeExecutionResult(actions=tuple(actions), next_node_id=node_id, status="wait")
        except Exception as exc:
            payload = {"event": "AI_SYSTEM_EXECUTOR_ERROR", "node_id": node_id, "tenant_id": str(getattr(session, "tenant_id", "")), "exception_class": type(exc).__name__, "exception_message": str(exc), "traceback": "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))}
            logger.exception("AI_SYSTEM_EXECUTOR_ERROR %s", sanitize_metadata(payload))
            message = self.GOOGLE_CALENDAR_CONNECTION_ERROR_MESSAGE if self._is_google_calendar_failure(exc) else self.FALLBACK_MESSAGE
            return self._fallback(db, session=session, node_id=node_id, runtime_input=runtime_input, reason=type(exc).__name__, message=message)

    def _execute_internal_runtime(self, db, *, snapshot: FlowV2Snapshot, session: Any, runtime_input, system_node_id: str) -> list[Any]:
        from app.flow_v2.executor import FlowV2Executor, FlowV2SessionStatus, MAX_RUNTIME_STEPS
        from app.flow_v2.node_executors import NodeExecutorRegistry

        registry = NodeExecutorRegistry(event_store=self.event_store, transition_resolver=self.transition_resolver)
        actions: list[Any] = []
        for step in range(MAX_RUNTIME_STEPS):
            current_node_id = str(getattr(session, "current_node_id", "") or "")
            node = snapshot.node_by_id.get(current_node_id)
            if node is None:
                raise RuntimeError(f"AI System internal current node is absent: {current_node_id}")
            node_id = str(node["id"])
            node_type = str(node.get("type") or FlowV2Executor._node_data(node).get("type") or "message")
            self.event_store.append(db, session=session, event_type=FlowV2EventType.NODE_ENTERED, node_id=node_id, payload={"ai_system_node_id": system_node_id, "internal": True})
            result = registry.get(node_type).execute(db, snapshot=snapshot, session=session, node=node, runtime_input=runtime_input)
            self.event_store.append(db, session=session, event_type=FlowV2EventType.NODE_EXECUTED, node_id=node_id, payload={"analytics_event": "AI_SYSTEM_INTERNAL_NODE_EXECUTED", "ai_system_node_id": system_node_id, "node_type": node_type, "status": result.status})
            logger.info("event=AI_SYSTEM_INTERNAL_NODE_EXECUTED system_node_id=%s node_id=%s node_type=%s status=%s step=%s", system_node_id, node_id, node_type, result.status, step + 1)
            actions.extend(result.actions)
            for action in result.actions:
                if isinstance(action, SendMessageAction):
                    logger.info("event=AI_SYSTEM_INTERNAL_RESPONSE system_node_id=%s node_id=%s text=%s", system_node_id, node_id, action.text[:500])
                    self.event_store.append(db, session=session, event_type=FlowV2EventType.OUTPUT_EMITTED, node_id=node_id, payload={"analytics_event": "AI_SYSTEM_INTERNAL_RESPONSE", "ai_system_node_id": system_node_id, "text": action.text})
            if self._looks_like_tool_node(node_type, node, result):
                logger.info("event=AI_SYSTEM_INTERNAL_TOOL_CALLED system_node_id=%s node_id=%s node_type=%s tenant_id=%s", system_node_id, node_id, node_type, getattr(session, "tenant_id", None))
                self.event_store.append(db, session=session, event_type=FlowV2EventType.OUTPUT_EMITTED, node_id=node_id, payload={"analytics_event": "AI_SYSTEM_INTERNAL_TOOL_CALLED", "ai_system_node_id": system_node_id, "node_type": node_type, "tenant_id": str(getattr(session, "tenant_id", ""))})
            self.event_store.append(db, session=session, event_type=FlowV2EventType.NODE_COMPLETED, node_id=node_id, payload={"ai_system_node_id": system_node_id, "internal": True})

            if result.status in {"wait", "scheduled"}:
                session.current_node_id = result.next_node_id or node_id
                session.status = str(FlowV2SessionStatus.WAITING)
                return actions
            if result.status == "complete" or FlowV2Executor._is_terminal_node(node):
                session.current_node_id = snapshot.start_node_id
                session.status = str(FlowV2SessionStatus.WAITING)
                return actions
            if not result.next_node_id:
                raise RuntimeError(f"AI System internal node {node_id} continued without next_node_id")
            session.current_node_id = result.next_node_id
            session.status = str(FlowV2SessionStatus.RUNNING)
        raise RuntimeError(f"AI System internal runtime exceeded max_steps={MAX_RUNTIME_STEPS}")

    @classmethod
    def _build_internal_snapshot(cls, outer_snapshot, *, node_id: str, system_type: str, internal_nodes: list[Any], internal_edges: list[Any]) -> FlowV2Snapshot:
        nodes = [cls._normalize_internal_node(item, system_node_id=node_id, system_type=system_type) for item in internal_nodes if isinstance(item, dict) and item.get("id") not in (None, "")]
        if not nodes:
            raise RuntimeError("AI System has no executable internal nodes")
        edges = [dict(edge) for edge in internal_edges if isinstance(edge, dict)]
        start_node_id = cls._find_start_node_id(nodes, edges)
        payload = {"nodes": nodes, "edges": edges, "start_node_id": start_node_id, "transitions": build_transitions_from_edges(edges)}
        return FlowV2Snapshot(flow_version_id=outer_snapshot.flow_version_id, tenant_id=outer_snapshot.tenant_id, hash=canonical_hash(payload), nodes=tuple(nodes), edges=tuple(edges), transitions=tuple(payload["transitions"]), start_node_id=start_node_id, snapshot_schema_version=outer_snapshot.snapshot_schema_version)

    @staticmethod
    def _normalize_internal_node(node: dict[str, Any], *, system_node_id: str, system_type: str) -> dict[str, Any]:
        normalized = dict(node)
        data = dict(normalized.get("data") if isinstance(normalized.get("data"), dict) else {})
        node_type = str(normalized.get("type") or data.get("type") or "message").strip()
        normalized["type"] = node_type
        data.setdefault("type", node_type)
        data.setdefault("compiled_from_ai_system", system_node_id)
        data.setdefault("agent_system_template_id", system_type)
        data.setdefault("ai_system_internal_type", node_type)
        normalized["data"] = data
        return normalized

    @staticmethod
    def _find_start_node_id(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> str:
        for node in nodes:
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            if node.get("isStart") or node.get("is_start") or data.get("isStart") or data.get("is_start") or node.get("type") == "start" or str(node.get("id")) == "start":
                return str(node["id"])
        targets = {str(edge.get("target") or edge.get("to") or edge.get("target_node_id")) for edge in edges if isinstance(edge, dict) and (edge.get("target") or edge.get("to") or edge.get("target_node_id")) not in (None, "")}
        for node in nodes:
            if str(node["id"]) not in targets:
                return str(node["id"])
        return str(nodes[0]["id"])

    def _resume_or_start_node_id(self, *, session: Any, system_node_id: str, internal_snapshot: FlowV2Snapshot) -> str:
        context = getattr(session, "context", None)
        state = context.get(self.INTERNAL_CONTEXT_KEY, {}).get(system_node_id, {}) if isinstance(context, dict) else {}
        current = str(state.get("current_node_id") or "") if isinstance(state, dict) else ""
        return current if current in internal_snapshot.node_by_id else internal_snapshot.start_node_id

    def _persist_internal_pointer(self, *, session: Any, system_node_id: str, current_node_id: str | None) -> None:
        context = getattr(session, "context", None)
        if not isinstance(context, dict):
            return
        runtime_state = dict(context.get(self.INTERNAL_CONTEXT_KEY) or {})
        runtime_state[system_node_id] = {"current_node_id": current_node_id}
        context[self.INTERNAL_CONTEXT_KEY] = runtime_state
        session.context = context

    @staticmethod
    def _internal_session(*, session: Any, current_node_id: str) -> Any:
        return _InternalRuntimeSession(parent=session, current_node_id=current_node_id)

    @staticmethod
    def _looks_like_tool_node(node_type: str, node: dict[str, Any], result: NodeExecutionResult) -> bool:
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        lowered = node_type.strip().lower()
        return lowered in {"tool", "mcp", "google_calendar", "calendar", "action"} or "calendar" in lowered or bool(data.get("tool_id") or data.get("toolId") or data.get("mcp_tool_ids") or data.get("mcpToolIds") or getattr(result, "intent", None) in {"calendar_create", "calendar_list", "calendar_delete"})

    @staticmethod
    def _is_google_calendar_failure(exc: BaseException) -> bool:
        cursor: BaseException | None = exc
        while cursor is not None:
            text = f"{type(cursor).__name__} {cursor}".lower()
            if "google_calendar" in text or "google calendar" in text:
                return True
            cursor = cursor.__cause__ or cursor.__context__
        return False

    def _fallback(self, db, *, session: Any, node_id: str, runtime_input, reason: str, message: str | None = None) -> NodeExecutionResult:
        text = message or self.FALLBACK_MESSAGE
        logger.info("event=AI_SYSTEM_INTERNAL_RESPONSE node_id=%s fallback=true reason=%s text=%s", node_id, reason, text)
        action = SendMessageAction(tenant_id=session.tenant_id, session_id=session.id, external_user_id=runtime_input.external_user_id, conversation_id=runtime_input.conversation_id, contact_id=runtime_input.contact_id, text=text, metadata={**runtime_input.metadata, "node_id": node_id, "intent": "ai_system_fallback", "fallback_reason": reason})
        self.event_store.append(db, session=session, event_type=FlowV2EventType.OUTPUT_EMITTED, node_id=node_id, payload={"analytics_event": "AI_SYSTEM_INTERNAL_RESPONSE", "fallback": True, "reason": reason, "text": text})
        return NodeExecutionResult(actions=(action,), next_node_id=node_id, status="wait")


__all__ = [
    "AiDispatcherNodeExecutor",
    "AiGreetingNodeExecutor",
    "AiCalendarAgentNodeExecutor",
    "AiSafeFallbackNodeExecutor",
    "AiSystemNodeExecutor",
]
