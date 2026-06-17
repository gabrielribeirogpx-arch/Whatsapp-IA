from __future__ import annotations

import copy
import logging
import re
import time
import uuid
from typing import Any

from sqlalchemy import select

from app.flow_v2.actions import SendMessageAction
from app.flow_v2.contracts import RuntimeInput
from app.flow_v2.models import FlowV2Session
from app.flow_v2.node_executors import NodeExecutorRegistry
from app.flow_v2.snapshot import FlowV2Snapshot, FlowV2SnapshotRepository
from app.flow_v2.transition_resolver import TransitionResolver
from app.models.flow import Flow, FlowVersion

logger = logging.getLogger(__name__)
SAFE_TOOL_ID_RE = re.compile(r"^[A-Za-z0-9_]{1,64}$")
SAFE_VAR_RE = re.compile(r"^[A-Za-z0-9_.]{1,160}$")
MAX_STEPS = 20


def _node_type(node: dict[str, Any]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    return str(node.get("type") or data.get("type") or "").strip()


def _safe_preview(value: Any, limit: int = 1200) -> Any:
    if isinstance(value, dict):
        return {str(k): _safe_preview(v, limit) for k, v in value.items() if not re.search(r"(api[-_]?key|token|secret|password)", str(k), re.I)}
    if isinstance(value, list):
        return [_safe_preview(v, limit) for v in value[:20]]
    if isinstance(value, str):
        return value[:limit]
    return value


def _set_path(target: dict[str, Any], path: str, value: Any) -> None:
    if not SAFE_VAR_RE.match(path or ""):
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


def _version_id_for_tool(db, tenant_id, tool_config: dict[str, Any]):
    flow_id = tool_config.get("flow_id") or tool_config.get("flowId")
    flow_version_id = tool_config.get("flow_version_id") or tool_config.get("flowVersionId")
    flow = db.execute(select(Flow).where(Flow.id == flow_id, Flow.tenant_id == tenant_id, Flow.is_deleted.is_(False))).scalar_one_or_none()
    if flow is None:
        return None, None, "tenant_or_flow_invalid"
    if flow_version_id:
        version = db.execute(select(FlowVersion).where(FlowVersion.id == flow_version_id, FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant_id, FlowVersion.is_published.is_(True))).scalar_one_or_none()
    else:
        version_id = getattr(flow, "published_version_id", None) or getattr(flow, "current_version_id", None)
        version = db.execute(select(FlowVersion).where(FlowVersion.id == version_id, FlowVersion.flow_id == flow.id, FlowVersion.tenant_id == tenant_id, FlowVersion.is_published.is_(True))).scalar_one_or_none() if version_id else None
    if version is None or not (getattr(flow, "is_active", False) or str(getattr(flow, "status", "")) == "published"):
        return flow, None, "flow_not_published_or_active"
    return flow, version, None


def _has_recursive_agent(snapshot: FlowV2Snapshot, parent_flow_id: str) -> bool:
    for node in snapshot.nodes:
        if _node_type(node) != "ai_agent":
            continue
        data = node.get("data") if isinstance(node.get("data"), dict) else {}
        if data.get("allow_subflow_tools", data.get("allowSubflowTools", False)) is not True:
            continue
        for tool in data.get("subflow_tools", data.get("subflowTools", [])) or []:
            if isinstance(tool, dict) and str(tool.get("flow_id") or tool.get("flowId") or "") == str(parent_flow_id):
                return True
    return False


def execute_subflow_tool(tenant_id, parent_flow_id, parent_session_id, parent_agent_node_id, tool_config: dict[str, Any], input_text: str | None, runtime_context, db) -> dict[str, Any]:
    started = time.monotonic()
    tool_id = str(tool_config.get("tool_id") or "").strip()
    base = {"tool_id": tool_id, "flow_id": str(tool_config.get("flow_id") or ""), "flow_version_id": str(tool_config.get("flow_version_id") or ""), "status": "error", "output": {}, "messages": [], "variables_written": {}, "error": None, "duration_ms": 0}
    if not SAFE_TOOL_ID_RE.match(tool_id):
        return {**base, "error": "invalid_tool_id"}
    if str(tool_config.get("flow_id") or "") == str(parent_flow_id):
        return {**base, "error": "direct_recursion_blocked"}
    flow, version, err = _version_id_for_tool(db, tenant_id, tool_config)
    if err:
        return {**base, "error": err}
    base.update({"flow_id": str(flow.id), "flow_version_id": str(version.id)})
    snapshot = FlowV2SnapshotRepository().load(db, tenant_id=tenant_id, flow_version_id=version.id)
    if _has_recursive_agent(snapshot, str(parent_flow_id)):
        return {**base, "error": "recursive_subflow_blocked"}

    timeout_seconds = min(60, max(3, int(tool_config.get("timeout_seconds") or tool_config.get("timeoutSeconds") or 20)))
    context = copy.deepcopy(getattr(runtime_context, "metadata", {}) or {})
    _set_path(context, str(tool_config.get("input_variable") or "agent.subflow_input"), str(input_text or ""))
    child = FlowV2Session(tenant_id=tenant_id, flow_version_id=version.id, contact_id=getattr(runtime_context, "contact_id", None), conversation_id=getattr(runtime_context, "conversation_id", None), external_user_id=f"subflow:{parent_session_id}:{tool_id}:{uuid.uuid4()}", status="running", current_node_id=snapshot.start_node_id, context=context)
    child.id = uuid.uuid4()
    child.metadata = {"execution_mode": "tool_subflow", "parent_session_id": str(parent_session_id), "started_by_agent_node_id": str(parent_agent_node_id)}
    runtime_input = RuntimeInput(tenant_id=tenant_id, flow_version_id=version.id, external_user_id=getattr(runtime_context, "external_user_id", "subflow"), message_text=str(input_text or ""), contact_id=getattr(runtime_context, "contact_id", None), conversation_id=getattr(runtime_context, "conversation_id", None), metadata={"execution_mode": "tool_subflow", "parent_session_id": str(parent_session_id), "last_message": str(input_text or "")})
    registry = NodeExecutorRegistry(event_store=_ToolEventStore(), transition_resolver=TransitionResolver(_ToolEventStore()))
    messages: list[str] = []
    steps = 0
    status = "success"
    error = None
    while child.current_node_id and steps < MAX_STEPS:
        if time.monotonic() - started > timeout_seconds:
            status, error = "timeout", "timeout"
            break
        node = snapshot.node_by_id.get(str(child.current_node_id))
        if not node:
            status, error = "error", "node_not_found"
            break
        if _node_type(node) == "ai_agent":
            status, error = "error", "nested_ai_agent_blocked"
            break
        result = registry.get(_node_type(node)).execute(db, snapshot=snapshot, session=child, node=node, runtime_input=runtime_input)
        steps += 1
        messages.extend([a.text for a in result.actions if isinstance(a, SendMessageAction) and getattr(a, "text", None)])
        if result.status in {"wait", "complete"} or not result.next_node_id:
            child.current_node_id = None
            break
        child.current_node_id = str(result.next_node_id)
    if steps >= MAX_STEPS and child.current_node_id:
        status, error = "error", "max_steps_exceeded"
    variables = _safe_preview(child.context if isinstance(child.context, dict) else {})
    output = {"text": str((variables.get("subflow") or {}).get("output") or (messages[-1] if messages else ""))[:4000], "variables": variables, "messages": messages}
    out_var = str(tool_config.get("output_variable") or f"agent.subflows.{tool_id}.output")
    if isinstance(getattr(runtime_context, "metadata", None), dict) and SAFE_VAR_RE.match(out_var):
        _set_path(runtime_context.metadata, out_var, output)
    duration_ms = int((time.monotonic() - started) * 1000)
    logger.info("[AI AGENT SUBFLOW] tenant_id=%s parent_flow_id=%s subflow_id=%s tool_id=%s status=%s duration_ms=%s steps=%s", tenant_id, parent_flow_id, flow.id, tool_id, status, duration_ms, steps)
    return {**base, "status": status, "output": output, "messages": messages, "variables_written": {out_var: output}, "error": error, "duration_ms": duration_ms, "steps": steps}


class _ToolEventStore:
    def append(self, *args, **kwargs):
        return None
