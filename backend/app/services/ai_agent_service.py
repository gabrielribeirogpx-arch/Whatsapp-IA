from __future__ import annotations

import ipaddress
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from app.services.llm_service import generate_answer_for_tenant

SAFE_VARIABLE_RE = re.compile(r"^[A-Za-z0-9_.]+$")
FORBIDDEN_NAME_PARTS = ("api_key", "apikey", "token", "secret", "password")
SENSITIVE_HEADER_RE = re.compile(r"(authorization|api[-_]?key|token|secret|password|cookie)", re.I)
PLACEHOLDER_TOOLS = {"criar_evento", "consultar_crm", "criar_pedido", "enviar_email", "transferir_humano"}
SUPPORTED_TOOLS = {"responder", "definir_variavel", "chamar_webhook", "executar_node", "executar_subflow", "finalizar"} | PLACEHOLDER_TOOLS


@dataclass
class AgentToolAction:
    type: str
    data: dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentRunResult:
    message: str | None = None
    actions: list[AgentToolAction] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    steps_count: int = 0
    final_tool: str | None = None
    status: str = "success"
    fallback_used: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


def _safe_json_loads(raw: str) -> dict[str, Any] | None:
    try:
        value = json.loads(str(raw or "").strip())
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _is_private_or_internal_url(url: str) -> bool:
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https" or not parsed.hostname:
        return True
    host = parsed.hostname.strip().lower()
    if host in {"localhost", "0.0.0.0"} or host.endswith(".localhost"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified


def validate_webhook_config(webhook: dict[str, Any]) -> str | None:
    url = str(webhook.get("url") or "").strip()
    method = str(webhook.get("method") or "POST").upper()
    if method not in {"GET", "POST"}:
        return "invalid_method"
    if _is_private_or_internal_url(url):
        return "internal_or_invalid_url"
    return None


def _sanitize_headers(headers: Any) -> dict[str, str]:
    if not isinstance(headers, dict):
        return {}
    return {str(k): str(v) for k, v in headers.items() if not SENSITIVE_HEADER_RE.search(str(k))}


def _validate_variable(name: Any, value: Any) -> tuple[bool, str | None]:
    name_str = str(name or "").strip()
    lowered = name_str.lower()
    if not name_str or not SAFE_VARIABLE_RE.match(name_str):
        return False, "invalid_name"
    if any(part in lowered for part in FORBIDDEN_NAME_PARTS):
        return False, "forbidden_name"
    if not (value is None or isinstance(value, (str, int, float, bool))):
        return False, "invalid_value_type"
    if isinstance(value, str) and len(value) > 4000:
        return False, "value_too_large"
    return True, None


def _summarize_tools(tools: list[str], webhooks: list[dict[str, Any]]) -> str:
    visible = [t for t in tools if t in SUPPORTED_TOOLS]
    webhook_ids = [str(w.get("id")) for w in webhooks if isinstance(w, dict) and w.get("id")]
    return json.dumps({"tools": visible, "webhook_ids": webhook_ids}, ensure_ascii=False)


def _call_webhook(webhook: dict[str, Any], payload: Any) -> dict[str, Any]:
    err = validate_webhook_config(webhook)
    if err:
        return {"ok": False, "error": err}
    timeout = min(max(int(webhook.get("timeout_seconds") or 10), 1), 15)
    method = str(webhook.get("method") or "POST").upper()
    body = None
    headers = {"Content-Type": "application/json", **_sanitize_headers(webhook.get("headers"))}
    if method == "POST":
        body = json.dumps(payload if isinstance(payload, dict) else {}, ensure_ascii=False)[:20000].encode("utf-8")
    req = urllib.request.Request(str(webhook["url"]), data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read(2000).decode("utf-8", errors="replace")
            return {"ok": 200 <= resp.status < 300, "status_code": resp.status, "body_preview": text[:500]}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return {"ok": False, "error": type(exc).__name__}


def run_agent_for_tenant(db: Session, tenant_id, input_text: str, instruction: str, allowed_tools: list[str], tool_configs: dict[str, Any] | None, memory_context: str | None = None, options: dict[str, Any] | None = None, node_tool_executor=None, subflow_tool_executor=None) -> AgentRunResult:
    started = time.monotonic()
    opts = options or {}
    fallback = str(opts.get("fallback_message") or "Não consegui concluir essa ação agora. Quer que eu encaminhe para um atendente?")
    max_steps = min(max(int(opts.get("max_steps") or 3), 1), 5)
    allowed = [str(t) for t in (allowed_tools or []) if str(t) in SUPPORTED_TOOLS and str(t) != "finalizar"]
    webhooks = [w for w in ((tool_configs or {}).get("webhooks") or []) if isinstance(w, dict)]
    node_tools = [t for t in ((tool_configs or {}).get("node_tools") or []) if isinstance(t, dict)]
    subflow_tools = [t for t in ((tool_configs or {}).get("subflow_tools") or []) if isinstance(t, dict)]
    blocked_tool_calls: list[dict[str, Any]] = []
    node_tool_calls: list[dict[str, Any]] = []
    subflow_tool_calls: list[dict[str, Any]] = []
    seen_subflow_inputs: set[tuple[str, str]] = set()
    seen_node_inputs: set[tuple[str, str]] = set()
    max_node_tool_calls = min(max(int(opts.get("max_node_tool_calls") or 3), 1), 5)
    max_subflow_calls = min(max(int(opts.get("max_subflow_calls") or 2), 1), 3)
    state: list[dict[str, Any]] = []
    result = AgentRunResult()
    if not allowed:
        return AgentRunResult(message=fallback, status="error", fallback_used=True, final_tool="responder", steps_count=0)
    for step in range(max_steps):
        system = "\n".join([
            str(instruction or "Você é um agente de atendimento. Use apenas as ferramentas permitidas."),
            "Retorne somente JSON válido. Não use markdown. Não exponha raciocínio interno; use thought_summary curto.",
            "Use apenas ferramentas permitidas. Para responder ao usuário, use responder. Não invente resultado de ferramenta.",
            "Ferramentas/webhooks permitidos: " + _summarize_tools(allowed, webhooks),
            "Ferramentas do fluxo disponíveis: " + json.dumps([{"tool_id": str(t.get("tool_id")), "label": str(t.get("label", ""))[:80], "description": str(t.get("description", ""))[:300]} for t in node_tools], ensure_ascii=False),
            "Subflows disponíveis como ferramenta executar_subflow: " + json.dumps([{"tool_id": str(t.get("tool_id")), "label": str(t.get("label", ""))[:80], "description": str(t.get("description", ""))[:300]} for t in subflow_tools], ensure_ascii=False),
            "Para executar subflow use somente {\"tool\":\"executar_subflow\",\"arguments\":{\"tool_id\":\"id_permitido\",\"input\":\"texto\",\"reason\":\"motivo curto\"}}. Não invente tool_id nem envie flow_id.",
        ])
        messages = [{"role": "system", "content": system}]
        if memory_context:
            messages.append({"role": "system", "content": "Histórico recente:\n" + str(memory_context)[:4000]})
        if state:
            messages.append({"role": "system", "content": "Estado/resultados anteriores:\n" + json.dumps(state[-5:], ensure_ascii=False)})
        messages.append({"role": "user", "content": str(input_text or "")[:12000]})
        raw = generate_answer_for_tenant(db, tenant_id, messages, options={k: v for k, v in {"chat_model": opts.get("chat_model"), "temperature": opts.get("temperature", 0.2), "max_tokens": opts.get("max_tokens", 1200)}.items() if v not in (None, "")})
        decision = _safe_json_loads(raw)
        result.steps_count = step + 1
        if not decision:
            return AgentRunResult(message=fallback, status="error", fallback_used=True, steps_count=step + 1, final_tool="responder")
        tool = str(decision.get("tool") or "").strip()
        args = decision.get("arguments") if isinstance(decision.get("arguments"), dict) else {}
        if tool not in allowed and tool != "finalizar":
            return AgentRunResult(message=fallback, status="error", fallback_used=True, steps_count=step + 1, final_tool=tool or None, tools_used=result.tools_used)
        result.tools_used.append(tool)
        result.final_tool = tool
        if tool == "responder":
            msg = str(args.get("message") or fallback)[:4000]
            result.message = msg
            result.actions.append(AgentToolAction("message", {"message": msg}))
            break
        if tool == "definir_variavel":
            ok, err = _validate_variable(args.get("name"), args.get("value"))
            if not ok:
                state.append({"tool": tool, "ok": False, "error": err})
                continue
            result.actions.append(AgentToolAction("set_variable", {"name": str(args.get("name")), "value": args.get("value")}))
            state.append({"tool": tool, "ok": True, "name": str(args.get("name"))})
            continue
        if tool == "executar_node":
            tool_id = str(args.get("tool_id") or "").strip()
            tool_input = str(args.get("input") or input_text or "")[:12000]
            match = next((t for t in node_tools if str(t.get("tool_id")) == tool_id), None)
            key = (tool_id, tool_input)
            if match is None or node_tool_executor is None:
                blocked_tool_calls.append({"tool_id": tool_id, "error": "node_tool_not_allowed"})
                state.append({"tool": tool, "tool_id": tool_id, "ok": False, "error": "node_tool_not_allowed"})
                continue
            if len(node_tool_calls) >= max_node_tool_calls or key in seen_node_inputs:
                blocked_tool_calls.append({"tool_id": tool_id, "error": "node_tool_limit_or_repeat"})
                state.append({"tool": tool, "tool_id": tool_id, "ok": False, "error": "node_tool_limit_or_repeat"})
                continue
            seen_node_inputs.add(key)
            tool_result = node_tool_executor(match, tool_input, str(args.get("reason") or "")[:200])
            node_tool_calls.append({"tool_id": tool_id, "status": tool_result.get("status"), "node_type": tool_result.get("node_type")})
            state.append({"tool": tool, "tool_id": tool_id, "ok": tool_result.get("status") == "success", "result": tool_result.get("output"), "error": tool_result.get("error")})
            continue
        if tool == "executar_subflow":
            tool_id = str(args.get("tool_id") or "").strip()
            tool_input = str(args.get("input") or input_text or "")[:12000]
            match = next((t for t in subflow_tools if str(t.get("tool_id")) == tool_id), None)
            key = (tool_id, tool_input)
            if match is None or subflow_tool_executor is None:
                blocked_tool_calls.append({"tool_id": tool_id, "error": "subflow_tool_not_allowed"})
                state.append({"tool": tool, "tool_id": tool_id, "ok": False, "error": "subflow_tool_not_allowed"})
                continue
            if len(subflow_tool_calls) >= max_subflow_calls or key in seen_subflow_inputs:
                blocked_tool_calls.append({"tool_id": tool_id, "error": "subflow_tool_limit_or_repeat"})
                state.append({"tool": tool, "tool_id": tool_id, "ok": False, "error": "subflow_tool_limit_or_repeat"})
                continue
            seen_subflow_inputs.add(key)
            tool_result = subflow_tool_executor(match, tool_input, str(args.get("reason") or "")[:200])
            subflow_tool_calls.append({"tool_id": tool_id, "status": tool_result.get("status"), "flow_id": tool_result.get("flow_id"), "duration_ms": tool_result.get("duration_ms")})
            state.append({"tool": tool, "tool_id": tool_id, "ok": tool_result.get("status") == "success", "result": tool_result.get("output"), "error": tool_result.get("error")})
            continue
        if tool == "chamar_webhook":
            webhook_id = str(args.get("webhook_id") or "")
            webhook = next((w for w in webhooks if str(w.get("id")) == webhook_id), None)
            if webhook is None:
                state.append({"tool": tool, "ok": False, "error": "webhook_not_allowed"})
                continue
            webhook_result = _call_webhook(webhook, args.get("payload") if isinstance(args.get("payload"), dict) else {})
            result.actions.append(AgentToolAction("webhook", {"webhook_id": webhook_id, "ok": webhook_result.get("ok"), "status_code": webhook_result.get("status_code")}))
            state.append({"tool": tool, "webhook_id": webhook_id, **webhook_result})
            continue
        if tool == "finalizar":
            break
        state.append({"tool": tool, "ok": False, "error": "not_implemented"})
    else:
        result.message = fallback
        result.actions.append(AgentToolAction("message", {"message": fallback}))
        result.status = "error"
        result.fallback_used = True
        result.final_tool = "responder"
    result.metadata = {"latency_ms": int((time.monotonic() - started) * 1000), "node_tools_used": node_tool_calls, "node_tool_calls_count": len(node_tool_calls), "subflow_tools_used": subflow_tool_calls, "subflow_calls_count": len(subflow_tool_calls), "subflow_results_summary": subflow_tool_calls, "subflow_errors": [c for c in subflow_tool_calls if c.get("status") != "success"], "timeout_count": len([c for c in subflow_tool_calls if c.get("status") == "timeout"]), "blocked_tool_calls": blocked_tool_calls, "max_steps_reached": result.fallback_used}
    return result
