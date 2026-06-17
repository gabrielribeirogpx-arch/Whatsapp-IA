from __future__ import annotations

import copy
import re
from typing import Any

from app.flow_v2.actions import SendMessageAction
from app.flow_v2.node_executors import NodeExecutorRegistry
from app.flow_v2.transition_resolver import TransitionResolver

ALLOWED_NODE_TOOL_TYPES = {"ai_classification", "ai_extraction", "ai_summary", "ai_response", "action", "condition", "message"}
SAFE_TOOL_ID_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")


def _node_type(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return str(node.get("type") or data.get("type") or "").strip()


def _safe_preview(value: Any, limit: int = 1200) -> Any:
    if isinstance(value, dict):
        return {str(k): _safe_preview(v, limit=limit) for k, v in value.items() if "secret" not in str(k).lower() and "token" not in str(k).lower() and "key" not in str(k).lower()}
    if isinstance(value, list):
        return [_safe_preview(v, limit=limit) for v in value[:20]]
    if isinstance(value, str):
        return value[:limit]
    return value


def execute_node_tool(tenant_id, flow, session, current_agent_node_id: str, tool_config: dict[str, Any], input_text: str | None, runtime_context, db) -> dict[str, Any]:
    """Execute an explicitly allowed flow node as a controlled AI-agent tool.

    The called node is executed against the same session context but its routing result is
    intentionally ignored: no edges are advanced and the main session pointer is not changed here.
    """
    tool_id = str(tool_config.get("tool_id") or "").strip()
    node_id = str(tool_config.get("node_id") or "").strip()
    base = {"tool_id": tool_id, "node_id": node_id, "node_type": None, "status": "error", "output": {}, "message_actions": [], "variables_written": {}, "error": None}
    if not SAFE_TOOL_ID_RE.match(tool_id):
        return {**base, "error": "invalid_tool_id"}
    nodes = getattr(flow, "node_by_id", None) or {str(n.get("id")): n for n in (getattr(flow, "nodes", None) or flow.get("nodes", []) if isinstance(flow, dict) else []) if isinstance(n, dict)}
    node = nodes.get(node_id)
    if not isinstance(node, dict):
        return {**base, "error": "node_not_in_flow"}
    node_type = _node_type(node)
    base["node_type"] = node_type
    if node_id == str(current_agent_node_id):
        return {**base, "error": "self_call_blocked"}
    if node_type == "ai_agent" or node_type not in ALLOWED_NODE_TOOL_TYPES:
        return {**base, "error": "node_type_not_allowed"}
    if str(getattr(flow, "tenant_id", tenant_id)) != str(tenant_id):
        return {**base, "error": "tenant_mismatch"}

    context_before = copy.deepcopy(session.context) if isinstance(getattr(session, "context", None), dict) else {}
    current_pointer = getattr(session, "current_node_id", None)
    runtime_input = copy.copy(runtime_context)
    if input_text:
        try:
            runtime_input.message_text = str(input_text)
            runtime_input.text = str(input_text)
            runtime_input.metadata = {**(getattr(runtime_input, "metadata", {}) or {}), "last_message": str(input_text), "tool_mode": True}
        except Exception:
            pass

    registry = NodeExecutorRegistry(event_store=_ToolEventStore(), transition_resolver=TransitionResolver(_ToolEventStore()))
    executor = registry.get(node_type)
    try:
        result = executor.execute(db, snapshot=flow, session=session, node=node, runtime_input=runtime_input)
    except Exception:
        session.context = context_before
        if current_pointer is not None:
            session.current_node_id = current_pointer
        return {**base, "error": "tool_execution_failed"}
    if current_pointer is not None:
        session.current_node_id = current_pointer

    context_after = session.context if isinstance(getattr(session, "context", None), dict) else {}
    variables_written = {k: v for k, v in context_after.items() if context_before.get(k) != v}
    if tool_config.get("pass_context", True) is False:
        session.context = context_before
        variables_written = {}
    output = {"status": result.status, "effects": [_safe_preview(a.as_effect()) for a in result.actions], "context_delta": _safe_preview(variables_written)}
    messages = [a.text for a in result.actions if isinstance(a, SendMessageAction)]
    if messages:
        output["messages"] = messages
    if tool_config.get("pass_context", True) is not False and isinstance(session.context, dict):
        out_var = str(tool_config.get("output_variable") or "").strip()
        if out_var:
            _set_path(session.context, out_var, output)
        session.context.setdefault("agent", {}).setdefault("tools", {}).setdefault(tool_id, {})["output"] = output
    return {**base, "status": "success", "output": output, "message_actions": messages, "variables_written": _safe_preview(variables_written), "error": None}


class _ToolEventStore:
    def append(self, *args, **kwargs):
        return None


def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
    if not re.match(r"^[A-Za-z0-9_.]{1,128}$", path or ""):
        return
    current = target
    parts = path.split(".")
    for part in parts[:-1]:
        nxt = current.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            current[part] = nxt
        current = nxt
    current[parts[-1]] = value
