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
from app.context_engine import UnifiedContextEngine
from app.services.circuit_breaker_service import CircuitBreakerOpen, check_circuit, record_failure, record_success
from app.services.execution_budget_service import ExecutionBudgetExceeded, ExecutionBudget
from app.services.long_term_memory_service import ALLOWED_FACT_TYPES, SECRET_RE, store_fact
from app.tools import ToolContext, ToolRegistry
from app.tools.adapters.mcp_tool_adapter import MCPToolAdapter
from app.tools.adapters.node_tool_adapter import NodeToolAdapter
from app.tools.adapters.subflow_tool_adapter import SubflowToolAdapter
from app.tools.adapters.webhook_tool_adapter import WebhookToolAdapter

SAFE_VARIABLE_RE = re.compile(r"^[A-Za-z0-9_.]+$")
FORBIDDEN_NAME_PARTS = ("api_key", "apikey", "token", "secret", "password")
SENSITIVE_HEADER_RE = re.compile(r"(authorization|api[-_]?key|token|secret|password|cookie)", re.I)
PLACEHOLDER_TOOLS = {"criar_evento", "consultar_crm", "criar_pedido", "enviar_email", "transferir_humano"}
SUPPORTED_TOOLS = {"responder", "definir_variavel", "chamar_webhook", "executar_node", "executar_subflow", "salvar_memoria", "chamar_mcp", "finalizar"} | PLACEHOLDER_TOOLS


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


def _call_webhook(webhook: dict[str, Any], payload: Any, budget: ExecutionBudget | None = None, tenant_id: Any | None = None) -> dict[str, Any]:
    if budget is not None:
        budget.consume_webhook_call()
    err = validate_webhook_config(webhook)
    if err:
        return {"ok": False, "error": err}
    timeout = min(max(int(webhook.get("timeout_seconds") or 10), 1), 15)
    if budget is not None:
        timeout = max(1, min(timeout, max(1, budget.remaining_ms() // 1000)))
    method = str(webhook.get("method") or "POST").upper()
    body = None
    headers = {"Content-Type": "application/json", **_sanitize_headers(webhook.get("headers"))}
    if method == "POST":
        body = json.dumps(payload if isinstance(payload, dict) else {}, ensure_ascii=False)[:20000].encode("utf-8")
    req = urllib.request.Request(str(webhook["url"]), data=body, headers=headers, method=method)
    host = (urlparse(str(webhook.get("url") or "")).hostname or "unknown").lower()
    circuit_key = f"webhook:{tenant_id or 'global'}:{host}"
    try:
        cb_meta = check_circuit(circuit_key)
    except CircuitBreakerOpen:
        return {"ok": False, "error": "circuit_open", "status": "circuit_open", "message": "Integração temporariamente indisponível."}
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read(2000).decode("utf-8", errors="replace")
            ok = 200 <= resp.status < 300
            if ok:
                record_success(circuit_key)
            elif resp.status >= 500 or resp.status == 429:
                record_failure(circuit_key, reason=f"webhook_status:{resp.status}")
            return {"ok": ok, "status_code": resp.status, "body_preview": text[:500], "circuit_breaker_checked": cb_meta.get("circuit_breaker_checked"), "circuit_breaker_key_hash": cb_meta.get("circuit_breaker_key_hash"), "circuit_breaker_state": cb_meta.get("circuit_breaker_state"), "circuit_breaker_open": False}
    except urllib.error.HTTPError as exc:
        if exc.code >= 500 or exc.code == 429:
            record_failure(circuit_key, reason=f"webhook_status:{exc.code}")
        return {"ok": False, "status_code": exc.code, "error": type(exc).__name__, "circuit_breaker_checked": cb_meta.get("circuit_breaker_checked"), "circuit_breaker_key_hash": cb_meta.get("circuit_breaker_key_hash"), "circuit_breaker_state": cb_meta.get("circuit_breaker_state"), "circuit_breaker_open": False}
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        record_failure(circuit_key, reason=f"webhook:{type(exc).__name__}")
        return {"ok": False, "error": type(exc).__name__, "circuit_breaker_checked": cb_meta.get("circuit_breaker_checked"), "circuit_breaker_key_hash": cb_meta.get("circuit_breaker_key_hash"), "circuit_breaker_state": cb_meta.get("circuit_breaker_state"), "circuit_breaker_open": False}


def run_agent_for_tenant(db: Session, tenant_id, input_text: str, instruction: str, allowed_tools: list[str], tool_configs: dict[str, Any] | None, memory_context: str | None = None, options: dict[str, Any] | None = None, node_tool_executor=None, subflow_tool_executor=None, mcp_tool_executor=None, budget: ExecutionBudget | None = None) -> AgentRunResult:
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
    mcp_tools = [t for t in ((tool_configs or {}).get("mcp_tools") or []) if isinstance(t, dict)]
    mcp_tool_calls: list[dict[str, Any]] = []
    seen_subflow_inputs: set[tuple[str, str]] = set()
    seen_node_inputs: set[tuple[str, str]] = set()
    max_node_tool_calls = min(max(int(opts.get("max_node_tool_calls") or 3), 1), 5)
    max_subflow_calls = min(max(int(opts.get("max_subflow_calls") or 2), 1), 3)
    max_mcp_calls = min(max(int(opts.get("max_mcp_calls") or 3), 0), 3)
    state: list[dict[str, Any]] = []
    result = AgentRunResult()
    tool_context = ToolContext(tenant_id=tenant_id, execution_budget=budget, trace_id=str(opts.get("trace_id") or opts.get("correlation_id") or ""), metadata={"source": "ai_agent"})
    tool_registry = ToolRegistry()
    tool_registry.register(NodeToolAdapter(node_tool_executor))
    tool_registry.register(SubflowToolAdapter(subflow_tool_executor))
    tool_registry.register(MCPToolAdapter(mcp_tool_executor))
    tool_registry.register(WebhookToolAdapter(_call_webhook, validate_webhook_config))
    if not allowed:
        return AgentRunResult(message=fallback, status="error", fallback_used=True, final_tool="responder", steps_count=0)
    try:
        package = UnifiedContextEngine(db).build(tenant_id=tenant_id, execution_context={"tenant_id": str(tenant_id), "trace_id": tool_context.trace_id, "tool_outputs": state}, budget=budget, flags={"include_short_memory": False, "include_long_memory": False, "include_rag_context": False})
        result.metadata["unified_context_engine"] = True
        if package.safe_metadata.get("context_reduced"):
            result.metadata["context_reduced"] = package.safe_metadata.get("context_reduced")
    except Exception:
        result.metadata["unified_context_engine"] = False
    for step in range(max_steps):
        system = "\n".join([
            str(instruction or "Você é um agente de atendimento. Use apenas as ferramentas permitidas."),
            "Retorne somente JSON válido. Não use markdown. Não exponha raciocínio interno; use thought_summary curto.",
            "Use apenas ferramentas permitidas. Para responder ao usuário, use responder. Não invente resultado de ferramenta.",
            "Ferramentas/webhooks permitidos: " + _summarize_tools(allowed, webhooks),
            "Ferramentas do fluxo disponíveis: " + json.dumps([{"tool_id": str(t.get("tool_id")), "label": str(t.get("label", ""))[:80], "description": str(t.get("description", ""))[:300]} for t in node_tools], ensure_ascii=False),
            "Subflows disponíveis como ferramenta executar_subflow: " + json.dumps([{"tool_id": str(t.get("tool_id")), "label": str(t.get("label", ""))[:80], "description": str(t.get("description", ""))[:300]} for t in subflow_tools], ensure_ascii=False),
            "Ferramentas MCP disponíveis como chamar_mcp: " + json.dumps([{"tool_id": str(t.get("tool_id")), "name": str(t.get("name", ""))[:120], "description": str(t.get("description", ""))[:300], "input_schema": t.get("input_schema") if isinstance(t.get("input_schema"), dict) else {}} for t in mcp_tools], ensure_ascii=False),
            "Para executar MCP use somente {\"tool\":\"chamar_mcp\",\"arguments\":{\"tool_id\":\"id_permitido\",\"input\":{}}}. Não invente tool_id, URL, headers ou credenciais.",
            "Para executar subflow use somente {\"tool\":\"executar_subflow\",\"arguments\":{\"tool_id\":\"id_permitido\",\"input\":\"texto\",\"reason\":\"motivo curto\"}}. Não invente tool_id nem envie flow_id.",
        ])
        messages = [{"role": "system", "content": system}]
        if memory_context:
            messages.append({"role": "system", "content": "Histórico recente:\n" + str(memory_context)[:4000]})
        if state:
            messages.append({"role": "system", "content": "Estado/resultados anteriores:\n" + json.dumps(state[-5:], ensure_ascii=False)})
        messages.append({"role": "user", "content": str(input_text or "")[:12000]})
        try:
            if budget is not None:
                approx_prompt = (len(system) + len(str(memory_context or "")) + len(str(input_text or ""))) // 4
                budget.consume_llm_call(prompt_tokens_estimate=approx_prompt, completion_tokens_estimate=int(opts.get("max_tokens") or 1200))
        except ExecutionBudgetExceeded:
            return AgentRunResult(message=fallback, status="budget_exceeded", fallback_used=True, steps_count=step, final_tool="responder", metadata={**(budget.safe_metadata() if budget else {}), "budget_exceeded": True})
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
            try:
                if budget is not None:
                    budget.consume_node_tool_call()
                registry_result = tool_registry.execute("node_tool", tool_id, tool_input, tool_context, {"node_tools": node_tools, "reason": str(args.get("reason") or "")[:200], "consume_budget": False})
                tool_result = {"status": "success" if registry_result.ok else "error", "output": registry_result.output, "error": registry_result.error_code, **(registry_result.metadata or {})}
            except ExecutionBudgetExceeded:
                return AgentRunResult(message=fallback, status="budget_exceeded", fallback_used=True, steps_count=step + 1, final_tool=tool, tools_used=result.tools_used, metadata={**(budget.safe_metadata() if budget else {}), "budget_exceeded": True})
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
            try:
                if budget is not None:
                    budget.consume_subflow_call()
                registry_result = tool_registry.execute("subflow_tool", tool_id, tool_input, tool_context, {"subflow_tools": subflow_tools, "reason": str(args.get("reason") or "")[:200], "consume_budget": False})
                tool_result = {"status": "success" if registry_result.ok else "error", "output": registry_result.output, "error": registry_result.error_code, **(registry_result.metadata or {})}
            except ExecutionBudgetExceeded:
                return AgentRunResult(message=fallback, status="budget_exceeded", fallback_used=True, steps_count=step + 1, final_tool=tool, tools_used=result.tools_used, metadata={**(budget.safe_metadata() if budget else {}), "budget_exceeded": True})
            subflow_tool_calls.append({"tool_id": tool_id, "status": tool_result.get("status"), "flow_id": tool_result.get("flow_id"), "duration_ms": tool_result.get("duration_ms")})
            state.append({"tool": tool, "tool_id": tool_id, "ok": tool_result.get("status") == "success", "result": tool_result.get("output"), "error": tool_result.get("error")})
            continue
        if tool == "chamar_mcp":
            tool_id = str(args.get("tool_id") or "").strip()
            tool_input = args.get("input") if isinstance(args.get("input"), dict) else {}
            match = next((t for t in mcp_tools if str(t.get("tool_id")) == tool_id), None)
            if match is None or mcp_tool_executor is None:
                blocked_tool_calls.append({"tool_id": tool_id, "error": "mcp_tool_not_allowed"})
                state.append({"tool": tool, "tool_id": tool_id, "ok": False, "error": "mcp_tool_not_allowed"})
                continue
            if len(mcp_tool_calls) >= max_mcp_calls:
                blocked_tool_calls.append({"tool_id": tool_id, "error": "mcp_tool_limit"})
                state.append({"tool": tool, "tool_id": tool_id, "ok": False, "error": "mcp_tool_limit"})
                continue
            try:
                registry_result = tool_registry.execute("mcp_tool", tool_id, tool_input, tool_context, {"mcp_tools": mcp_tools})
                tool_result = {"ok": registry_result.ok, "status": "success" if registry_result.ok else "error", "result": registry_result.output, "error": registry_result.error_code, **(registry_result.metadata or {})}
            except ExecutionBudgetExceeded:
                return AgentRunResult(message=fallback, status="budget_exceeded", fallback_used=True, steps_count=step + 1, final_tool=tool, tools_used=result.tools_used, metadata={**(budget.safe_metadata() if budget else {}), "budget_exceeded": True})
            mcp_call = {"tool_id": tool_id, "status": tool_result.get("status"), "latency_ms": tool_result.get("latency_ms"), "error": tool_result.get("error")}
            mcp_tool_calls.append(mcp_call)
            state.append({"tool": tool, "tool_id": tool_id, "ok": tool_result.get("ok") is True, "result": tool_result.get("result"), "error": tool_result.get("error")})
            continue
        if tool == "salvar_memoria":
            memory_ctx = (tool_configs or {}).get("memory_context") if isinstance(tool_configs, dict) else {}
            contact_id = memory_ctx.get("contact_id") if isinstance(memory_ctx, dict) else None
            fact_text = str(args.get("fact_text") or "").strip()
            fact_type = str(args.get("fact_type") or "custom").strip()
            if not contact_id:
                state.append({"tool": tool, "ok": False, "error": "missing_contact"})
                continue
            if not fact_text or len(fact_text) > 1000 or SECRET_RE.search(fact_text):
                state.append({"tool": tool, "ok": False, "error": "invalid_or_sensitive_fact"})
                continue
            if fact_type not in ALLOWED_FACT_TYPES:
                fact_type = "custom"
            try:
                row = store_fact(db, tenant_id, contact_id, fact_text, fact_type=fact_type, importance_score=args.get("importance_score", 0.7), conversation_id=memory_ctx.get("conversation_id"), session_id=memory_ctx.get("session_id"), source="ai_agent_tool", metadata={"source": "ai_agent_tool"})
                state.append({"tool": tool, "ok": bool(row), "memory_id": str(row.id) if row else None})
            except Exception as exc:
                state.append({"tool": tool, "ok": False, "error": type(exc).__name__})
            continue
        if tool == "chamar_webhook":
            webhook_id = str(args.get("webhook_id") or "")
            webhook = next((w for w in webhooks if str(w.get("id")) == webhook_id), None)
            if webhook is None:
                state.append({"tool": tool, "ok": False, "error": "webhook_not_allowed"})
                continue
            try:
                registry_result = tool_registry.execute("webhook", webhook_id, args.get("payload") if isinstance(args.get("payload"), dict) else {}, tool_context, {"webhooks": webhooks})
                webhook_result = {"ok": registry_result.ok, **(registry_result.output if isinstance(registry_result.output, dict) else {}), "error": registry_result.error_code}
            except ExecutionBudgetExceeded:
                return AgentRunResult(message=fallback, status="budget_exceeded", fallback_used=True, steps_count=step + 1, final_tool=tool, tools_used=result.tools_used, metadata={**(budget.safe_metadata() if budget else {}), "budget_exceeded": True})
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
    result.metadata = {"latency_ms": int((time.monotonic() - started) * 1000), "node_tools_used": node_tool_calls, "node_tool_calls_count": len(node_tool_calls), "subflow_tools_used": subflow_tool_calls, "subflow_calls_count": len(subflow_tool_calls), "subflow_results_summary": subflow_tool_calls, "mcp_tools_used": mcp_tool_calls, "mcp_call_count": len(mcp_tool_calls), "mcp_latency_ms": sum(int(c.get("latency_ms") or 0) for c in mcp_tool_calls), "mcp_status": "error" if any(c.get("status") != "success" for c in mcp_tool_calls) else ("success" if mcp_tool_calls else "not_used"), "mcp_error_sanitized": next((c.get("error") for c in mcp_tool_calls if c.get("error")), None), "subflow_errors": [c for c in subflow_tool_calls if c.get("status") != "success"], "timeout_count": len([c for c in subflow_tool_calls if c.get("status") == "timeout"]), "blocked_tool_calls": blocked_tool_calls, "max_steps_reached": result.fallback_used, "memory_saved_count": len([item for item in state if item.get("tool") == "salvar_memoria" and item.get("ok")]), **(budget.safe_metadata() if budget else {})}
    return result
