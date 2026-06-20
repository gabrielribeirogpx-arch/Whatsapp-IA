from __future__ import annotations

import ipaddress
import json
import logging
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
from app.observability import TraceContext, TraceEventType, record_event
from app.tools.adapters.subflow_tool_adapter import SubflowToolAdapter
from app.tools.adapters.webhook_tool_adapter import WebhookToolAdapter

SAFE_VARIABLE_RE = re.compile(r"^[A-Za-z0-9_.]+$")
FORBIDDEN_NAME_PARTS = ("api_key", "apikey", "token", "secret", "password")
SENSITIVE_HEADER_RE = re.compile(r"(authorization|api[-_]?key|token|secret|password|cookie)", re.I)
PLACEHOLDER_TOOLS = {"criar_evento", "consultar_crm", "criar_pedido", "enviar_email", "transferir_humano"}
SUPPORTED_TOOLS = {"responder", "definir_variavel", "chamar_webhook", "executar_node", "executar_subflow", "salvar_memoria", "chamar_mcp", "finalizar"} | PLACEHOLDER_TOOLS

logger = logging.getLogger(__name__)


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



def _format_tool_result_context(item: dict[str, Any]) -> str:
    normalized = item.get("normalized_result") if isinstance(item.get("normalized_result"), dict) else {}
    display_type = normalized.get("type") or normalized.get("tool") or item.get("tool_id") or item.get("tool")
    data = normalized.get("data") if isinstance(normalized.get("data"), dict) else {}
    return "\n".join([
        "Tool result:",
        f"Tool:\n{display_type}",
        "",
        f"Success:\n{str(normalized.get('ok') if 'ok' in normalized else item.get('ok')).lower()}",
        "",
        f"Summary:\n{normalized.get('summary') or normalized.get('result_text') or ''}",
        "",
        "Data:\n" + json.dumps(data, ensure_ascii=False, indent=2),
    ])


def _format_universal_tool_response(item: dict[str, Any]) -> str:
    normalized = item.get("normalized_result") if isinstance(item.get("normalized_result"), dict) else {}
    summary = str(normalized.get("summary") or "").strip()
    result_text = str(normalized.get("result_text") or "").strip()
    if summary:
        return f"Perfeito! {summary}." if not summary.endswith((".", "!", "?")) else f"Perfeito! {summary}"
    if result_text:
        return result_text
    return "Perfeito! Sua solicitação foi concluída com sucesso."

def _json_log(event: str, **metadata: Any) -> None:
    logger.info("event=%s %s", event, json.dumps(metadata, ensure_ascii=False, default=str))


def _fallback_result(fallback: str, reason: str, *, step: int = 0, final_tool: str | None = "responder", tools_used: list[str] | None = None, metadata: dict[str, Any] | None = None, status: str = "error") -> AgentRunResult:
    _json_log("AI_AGENT_FALLBACK_REASON", reason=reason, step=step, final_tool=final_tool)
    _json_log("AI_AGENT_FINAL_RESPONSE", response=fallback, fallback=True, reason=reason)
    _json_log("AI_AGENT_FINISHED", status=status, fallback_used=True, reason=reason)
    return AgentRunResult(message=fallback, status=status, fallback_used=True, final_tool=final_tool, steps_count=step, tools_used=tools_used or [], metadata=metadata or {})


def _latest_valid_result_text(state: list[dict[str, Any]]) -> str | None:
    item = _latest_valid_tool_result(state)
    if not item:
        return None
    normalized = item.get("normalized_result") if isinstance(item.get("normalized_result"), dict) else {}
    return str(normalized.get("result_text") or normalized.get("summary") or "").strip() or None


def _latest_valid_tool_result(state: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next((item for item in reversed(state) if item.get("ok") is True and isinstance(item.get("normalized_result"), dict)), None)


def _extract_final_response_text(parsed: dict[str, Any], *, tool: str | None = None) -> str | None:
    """Extract the final user-facing response from supported LLM JSON shapes."""
    if not isinstance(parsed, dict):
        return None
    arguments = parsed.get("arguments") if isinstance(parsed.get("arguments"), dict) else {}
    if tool == "responder":
        for key in ("text", "message", "response"):
            text = str(arguments.get(key) or "").strip()
            if text:
                return text
    for key in ("response", "message", "text", "answer"):
        text = str(parsed.get(key) or "").strip()
        if text:
            return text
    for key in ("text", "message", "response"):
        text = str(arguments.get(key) or "").strip()
        if text:
            return text
    return None


def _first_text_value(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _normalize_tool_decision(decision: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
    raw_call: dict[str, Any] = decision
    if isinstance(decision.get("tool_calls"), list):
        raw_call = next((call for call in decision.get("tool_calls") or [] if isinstance(call, dict)), decision)
    args = raw_call.get("arguments") if isinstance(raw_call.get("arguments"), dict) else {}
    tool = _first_text_value(raw_call.get("tool"), decision.get("tool"))
    return tool, args, raw_call


def _normalize_mcp_tool_call(raw_call: dict[str, Any], args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    tool_id = _first_text_value(args.get("tool_id"), args.get("id"), raw_call.get("tool_id"), raw_call.get("id"))
    if isinstance(args.get("input"), dict):
        tool_input = args.get("input")
    elif isinstance(raw_call.get("input"), dict):
        tool_input = raw_call.get("input")
    else:
        tool_input = {}
    return tool_id, tool_input

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
    trace = TraceContext.from_mapping(options or {}, tenant_id=tenant_id)
    record_event(db, trace, TraceEventType.AI_AGENT_STARTED, metadata={"allowed_tools": allowed_tools, "has_memory_context": bool(memory_context)})
    _json_log("AI_AGENT_STARTED", allowed_tools=allowed_tools, has_memory_context=bool(memory_context))
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
        return _fallback_result(fallback, "no_allowed_tools", step=0)
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
            result_text = _latest_valid_result_text(state)
            tool_results = [item for item in state[-5:] if item.get("tool")]
            context_payload = {"tool_results": tool_results, "result_text": result_text}
            latest_tool_result = _latest_valid_tool_result(state)
            if latest_tool_result:
                context_payload["tool_result_context"] = _format_tool_result_context(latest_tool_result)
            messages.append({"role": "system", "content": "Estado/resultados anteriores:\n" + "\n\n".join(_format_tool_result_context(item) for item in state[-5:] if isinstance(item.get("normalized_result"), dict))})
            _json_log("AI_AGENT_ASSISTANT_CONTEXT", assistant_context=messages[-1]["content"])
            if result_text or latest_tool_result:
                messages.append({"role": "assistant", "name": "assistant_context", "content": json.dumps(context_payload, ensure_ascii=False)})
        messages.append({"role": "user", "content": str(input_text or "")[:12000]})
        _json_log("AI_AGENT_FINAL_LLM_INPUT" if state else "AI_AGENT_TOOL_SELECTION_BEGIN", step=step + 1, messages=messages, state_keys=sorted({key for item in state for key in item.keys()}))
        try:
            if budget is not None:
                approx_prompt = (len(system) + len(str(memory_context or "")) + len(str(input_text or ""))) // 4
                budget.consume_llm_call(prompt_tokens_estimate=approx_prompt, completion_tokens_estimate=int(opts.get("max_tokens") or 1200))
        except ExecutionBudgetExceeded:
            return AgentRunResult(message=fallback, status="budget_exceeded", fallback_used=True, steps_count=step, final_tool="responder", metadata={**(budget.safe_metadata() if budget else {}), "budget_exceeded": True})
        llm_started = time.monotonic()
        record_event(db, trace, TraceEventType.LLM_REQUEST, metadata={"step": step + 1, "model": opts.get("chat_model"), "messages_count": len(messages), "prompt": "[REDACTED]"})
        try:
            raw = generate_answer_for_tenant(db, tenant_id, messages, options={k: v for k, v in {"chat_model": opts.get("chat_model"), "temperature": opts.get("temperature", 0.2), "max_tokens": opts.get("max_tokens", 1200)}.items() if v not in (None, "")})
        except Exception as exc:
            logger.exception("event=AI_AGENT_FALLBACK_REASON reason=llm_failed step=%s error=%s", step + 1, type(exc).__name__)
            return _fallback_result(fallback, "llm_failed", step=step + 1, tools_used=result.tools_used)
        record_event(db, trace, TraceEventType.LLM_RESPONSE, duration_ms=int((time.monotonic() - llm_started) * 1000), metadata={"step": step + 1, "response_size": len(str(raw or ""))})
        _json_log("AI_AGENT_FINAL_LLM_OUTPUT", step=step + 1, raw_output=raw, phase="final_response" if state else "tool_selection")
        decision = _safe_json_loads(raw)
        result.steps_count = step + 1
        if not decision:
            successful_tool_result = _latest_valid_tool_result(state)
            if successful_tool_result:
                msg = (_format_universal_tool_response(successful_tool_result))[:4000]
                _json_log("AI_AGENT_RESPONSE_EXTRACTION_FAILED", step=step + 1, reason="invalid_llm_json", has_tool_result_text=True)
                _json_log("AI_AGENT_UNIVERSAL_FALLBACK", response=msg, source="tool_result_after_invalid_llm_json")
                _json_log("AI_AGENT_FINAL_RESPONSE", response=msg, fallback=False, source="tool_result_after_invalid_llm_json")
                result.message = msg
                result.actions.append(AgentToolAction("message", {"message": msg}))
                result.status = "success"
                result.fallback_used = False
                result.final_tool = "responder"
                break
            return _fallback_result(fallback, "invalid_llm_json", step=step + 1)
        tool, args, raw_call = _normalize_tool_decision(decision)
        response_text = _extract_final_response_text(decision, tool=tool)
        if state or tool == "responder" or response_text:
            _json_log("AI_AGENT_FINAL_RESPONSE_PARSED", step=step + 1, tool=tool, has_response_text=bool(response_text), parsed=decision)
        if response_text:
            _json_log("AI_AGENT_RESPONSE_TEXT_EXTRACTED", step=step + 1, tool=tool, source="arguments" if tool == "responder" and isinstance(decision.get("arguments"), dict) and any(str(decision["arguments"].get(key) or "").strip() == response_text for key in ("text", "message", "response")) else "root", response_size=len(response_text))
        if tool == "chamar_mcp":
            selected_tool_id, _selected_tool_input = _normalize_mcp_tool_call(raw_call, args)
            selected_match = next((t for t in mcp_tools if str(t.get("tool_id")) == selected_tool_id), None)
            selected_tool_type = "mcp_tool" if selected_match is not None else tool
        else:
            selected_tool_id = _first_text_value(args.get("tool_id"), args.get("webhook_id"), raw_call.get("tool_id"), raw_call.get("id"), tool)
            selected_match = next((t for t in [*node_tools, *subflow_tools] if str(t.get("tool_id")) == selected_tool_id), None)
            selected_tool_type = tool
        _json_log("AI_AGENT_TOOL_SELECTED", tool_id=selected_tool_id, tool_name=(selected_match or {}).get("name") or (selected_match or {}).get("label") or tool, tool_type=selected_tool_type, step=step + 1)
        if response_text and (not tool or tool == "finalizar"):
            msg = response_text[:4000]
            _json_log("AI_AGENT_FINAL_RESPONSE", step=step + 1, response=msg, response_size=len(msg), fallback=False)
            result.message = msg
            result.actions.append(AgentToolAction("message", {"message": msg}))
            result.status = "success"
            result.fallback_used = False
            result.final_tool = "responder"
            break
        if tool not in allowed and tool != "finalizar":
            successful_tool_result = _latest_valid_tool_result(state)
            if successful_tool_result:
                msg = (_format_universal_tool_response(successful_tool_result))[:4000]
                _json_log("AI_AGENT_RESPONSE_EXTRACTION_FAILED", step=step + 1, reason="tool_not_allowed", has_tool_result_text=True, tool=tool)
                _json_log("AI_AGENT_UNIVERSAL_FALLBACK", response=msg, source="tool_result_after_tool_not_allowed", tool=tool)
                _json_log("AI_AGENT_FINAL_RESPONSE", response=msg, fallback=False, source="tool_result_after_tool_not_allowed", tool=tool)
                result.message = msg
                result.actions.append(AgentToolAction("message", {"message": msg}))
                result.status = "success"
                result.fallback_used = False
                result.final_tool = "responder"
                break
            return _fallback_result(fallback, "tool_not_allowed", step=step + 1, final_tool=tool or None, tools_used=result.tools_used)
        result.tools_used.append(tool)
        result.final_tool = tool
        if tool == "responder":
            successful_tool_result = _latest_valid_tool_result(state)
            if response_text:
                msg = response_text[:4000]
                fallback_used = False
            elif successful_tool_result:
                msg = (_format_universal_tool_response(successful_tool_result))[:4000]
                fallback_used = False
                _json_log("AI_AGENT_RESPONSE_EXTRACTION_FAILED", step=step + 1, reason="responder_without_text", has_tool_result_text=True)
            else:
                msg = fallback[:4000]
                fallback_used = True
                _json_log("AI_AGENT_RESPONSE_EXTRACTION_FAILED", step=step + 1, reason="responder_without_text", has_tool_result_text=False)
            _json_log("AI_AGENT_FINAL_RESPONSE", step=step + 1, response=msg, response_size=len(msg), fallback=fallback_used)
            result.message = msg
            result.actions.append(AgentToolAction("message", {"message": msg}))
            result.status = "success" if not fallback_used else "error"
            result.fallback_used = fallback_used
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
            tool_id, tool_input = _normalize_mcp_tool_call(raw_call, args)
            match = next((t for t in mcp_tools if str(t.get("tool_id")) == tool_id), None)
            if match is None or mcp_tool_executor is None:
                allowed_tool_ids = [str(t.get("tool_id")) for t in mcp_tools if t.get("tool_id") is not None]
                _json_log("AI_AGENT_MCP_TOOL_RESOLUTION_FAILED", tool_id=tool_id, allowed_tool_ids=allowed_tool_ids, raw_call=raw_call)
                blocked_tool_calls.append({"tool_id": tool_id, "error": "mcp_tool_not_allowed"})
                state.append({"tool": tool, "tool_id": tool_id, "ok": False, "error": "mcp_tool_not_allowed"})
                continue
            if len(mcp_tool_calls) >= max_mcp_calls:
                blocked_tool_calls.append({"tool_id": tool_id, "error": "mcp_tool_limit"})
                state.append({"tool": tool, "tool_id": tool_id, "ok": False, "error": "mcp_tool_limit"})
                continue
            _json_log("AI_AGENT_TOOL_CALL_BEGIN", tool_id=tool_id, tool_name=match.get("name"), tool_type="mcp_tool", input=tool_input)
            try:
                registry_result = tool_registry.execute("mcp_tool", tool_id, tool_input, tool_context, {"mcp_tools": mcp_tools})
                tool_result = {"ok": registry_result.ok, "status": "success" if registry_result.ok else "error", "result": registry_result.output, "structured_content": registry_result.structured_content, "error": registry_result.error_code, **(registry_result.metadata or {})}
                _json_log("AI_AGENT_TOOL_CALL_RESULT", ok=tool_result.get("ok"), raw_result=tool_result.get("result"), error=tool_result.get("error"))
            except ExecutionBudgetExceeded:
                return AgentRunResult(message=fallback, status="budget_exceeded", fallback_used=True, steps_count=step + 1, final_tool=tool, tools_used=result.tools_used, metadata={**(budget.safe_metadata() if budget else {}), "budget_exceeded": True})
            normalized = registry_result.normalized_result.to_dict() if registry_result.normalized_result else (registry_result.output if isinstance(registry_result.output, dict) else {})
            _json_log("AI_AGENT_TOOL_NORMALIZED", tool_original=tool_id, normalized_result=normalized)
            _json_log("AI_AGENT_TOOL_RESULT_MODEL", tool_original=tool_id, normalized_result=normalized)
            error = normalized.get("error") if isinstance(normalized.get("error"), dict) else None
            status = "success" if normalized.get("ok") is True else "error"
            mcp_call = {"tool_id": tool_id, "status": status, "latency_ms": tool_result.get("latency_ms"), "error": (error or {}).get("code")}
            mcp_tool_calls.append(mcp_call)
            logger.info("event=AI_AGENT_TOOL_RESULT_RECEIVED tool_type=mcp_tool tool_id=%s ok=%s has_text=%s", tool_id, normalized.get("ok") is True, bool(normalized.get("result_text")))
            if not normalized.get("result_text") and not normalized.get("data"):
                _json_log("AI_AGENT_FALLBACK_REASON", reason="mcp_no_text", tool_id=tool_id, ok=normalized.get("ok") is True)
            state.append({"tool": tool, "tool_id": tool_id, "tool_name": match.get("name"), "tool_type": "mcp_tool", "ok": normalized.get("ok") is True, "normalized_result": normalized, "error": (error or {}).get("code")})
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
        successful_tool_result = _latest_valid_tool_result(state)
        if successful_tool_result:
            result.message = _format_universal_tool_response(successful_tool_result)[:4000]
            result.actions.append(AgentToolAction("message", {"message": result.message}))
            result.status = "success"
            result.fallback_used = False
            result.final_tool = "responder"
            logger.info("event=AI_AGENT_FINAL_RESPONSE response_size=%s source=tool_result", len(result.message))
        else:
            logger.warning("event=AI_AGENT_FALLBACK_REASON reason=max_steps_or_no_valid_tool_text")
            result.message = fallback
            result.actions.append(AgentToolAction("message", {"message": fallback}))
            result.status = "error"
            result.fallback_used = True
            result.final_tool = "responder"
    total_latency_ms = int((time.monotonic() - started) * 1000)
    _json_log("AI_AGENT_FINISHED", status=result.status, final_tool=result.final_tool, tools_used=result.tools_used, fallback_used=result.fallback_used)
    record_event(db, trace, TraceEventType.AI_AGENT_FINISHED, duration_ms=total_latency_ms, metadata={"status": result.status, "final_tool": result.final_tool, "tools_used": result.tools_used})
    result.metadata = {"latency_ms": total_latency_ms, "node_tools_used": node_tool_calls, "node_tool_calls_count": len(node_tool_calls), "subflow_tools_used": subflow_tool_calls, "subflow_calls_count": len(subflow_tool_calls), "subflow_results_summary": subflow_tool_calls, "mcp_tools_used": mcp_tool_calls, "mcp_call_count": len(mcp_tool_calls), "mcp_latency_ms": sum(int(c.get("latency_ms") or 0) for c in mcp_tool_calls), "mcp_status": "error" if any(c.get("status") != "success" for c in mcp_tool_calls) else ("success" if mcp_tool_calls else "not_used"), "mcp_error_sanitized": next((c.get("error") for c in mcp_tool_calls if c.get("error")), None), "subflow_errors": [c for c in subflow_tool_calls if c.get("status") != "success"], "timeout_count": len([c for c in subflow_tool_calls if c.get("status") == "timeout"]), "blocked_tool_calls": blocked_tool_calls, "max_steps_reached": result.fallback_used, "memory_saved_count": len([item for item in state if item.get("tool") == "salvar_memoria" and item.get("ok")]), **(budget.safe_metadata() if budget else {})}
    return result
