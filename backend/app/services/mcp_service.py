from __future__ import annotations

import json
import logging
import socket
import time
import uuid
from typing import Any
from urllib.parse import urlparse

import requests
from jsonschema import ValidationError, validate
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant_mcp import TenantMCPServer, TenantMCPTool
from app.utils.encryption import decrypt_secret, encrypt_secret
from app.services.execution_budget_service import ExecutionBudget, ExecutionBudgetExceeded
from app.services.circuit_breaker_service import CircuitBreakerOpen, check_circuit, record_failure, record_success
from app.observability import TraceContext, TraceEventType, record_event
from app.services.google_calendar_service import GoogleCalendarService

logger = logging.getLogger(__name__)
ALLOWED_TRANSPORTS = {"http", "sse", "stdio_future"}
MAX_TIMEOUT_SECONDS = 15
MAX_TOOLS_PER_TENANT = 100
SENSITIVE_KEYS = ("api_key", "apikey", "token", "secret", "password", "authorization", "cookie")


class MCPError(ValueError):
    pass

CALENDAR_TOOL_IDS = {"calendar_create_event", "calendar_list_events", "calendar_check_availability", "calendar_delete_event"}


def _call_builtin_calendar_tool(db: Session, tenant_id: uuid.UUID, tool_id: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
    args = arguments if isinstance(arguments, dict) else {}
    service = GoogleCalendarService(db, tenant_id)
    if tool_id == "calendar_create_event":
        result = service.create_event(**args)
    elif tool_id == "calendar_list_events":
        result = service.list_events(**args)
    elif tool_id == "calendar_check_availability":
        result = service.check_availability(**args)
    elif tool_id == "calendar_delete_event":
        result = service.delete_event(str(args.get("event_id") or args.get("id") or ""))
    else:
        raise MCPError("Ferramenta MCP não encontrada para este workspace.")
    return {
        "ok": result.get("ok") is True,
        "status": "success" if result.get("ok") is True else "error",
        "tool_id": tool_id,
        "tool_name": tool_id,
        "latency_ms": 0,
        "result": {"structuredContent": {"ok": result.get("ok") is True, "tool": tool_id, "result": result if result.get("ok") is True else {}, "error": result.get("message") if result.get("ok") is not True else None}},
        "error": result.get("message") if result.get("ok") is not True else None,
    }


def _is_sensitive_key(key: str) -> bool:
    lowered = str(key).lower()
    return any(part in lowered for part in SENSITIVE_KEYS)


def sanitize_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return "[TRUNCATED]"
    if isinstance(value, dict):
        return {str(k): ("[REDACTED]" if _is_sensitive_key(str(k)) else sanitize_value(v, depth=depth + 1)) for k, v in value.items()}
    if isinstance(value, list):
        return [sanitize_value(v, depth=depth + 1) for v in value[:50]]
    if isinstance(value, str):
        return value[:4000]
    return value


def _encrypt_config(config: dict[str, Any] | None) -> dict[str, Any] | None:
    if not config:
        return None
    encrypted: dict[str, Any] = {}
    for key, value in config.items():
        encrypted[str(key)] = encrypt_secret(str(value)) if _is_sensitive_key(str(key)) and value not in (None, "") else value
    return encrypted


def _decrypt_config(config: dict[str, Any] | None) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in (config or {}).items():
        out[str(key)] = decrypt_secret(value) if isinstance(value, str) and value.startswith("enc:") else value
    return out


def _validate_public_https_url(server_url: str | None) -> str:
    url = str(server_url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise MCPError("MCP MVP aceita apenas URLs HTTPS públicas.")
    host = parsed.hostname.strip().lower()
    if host in {"localhost", "0.0.0.0"} or host.endswith(".localhost") or host.endswith(".internal") or host.endswith(".local"):
        raise MCPError("URL MCP interna não é permitida.")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise MCPError("Host MCP inválido ou não resolvível.") from exc
    import ipaddress
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            raise MCPError("URL MCP resolve para rede privada/interna.")
    return url


def _server(db: Session, tenant_id: uuid.UUID, server_id: uuid.UUID) -> TenantMCPServer:
    row = db.execute(select(TenantMCPServer).where(TenantMCPServer.tenant_id == tenant_id, TenantMCPServer.id == server_id)).scalars().first()
    if not row:
        raise MCPError("Servidor MCP não encontrado para este workspace.")
    return row


def _tool(db: Session, tenant_id: uuid.UUID, tool_id: uuid.UUID) -> TenantMCPTool:
    row = db.execute(select(TenantMCPTool).where(TenantMCPTool.tenant_id == tenant_id, TenantMCPTool.id == tool_id)).scalars().first()
    if not row:
        raise MCPError("Ferramenta MCP não encontrada para este workspace.")
    return row


def list_mcp_servers(db: Session, tenant_id: uuid.UUID) -> list[TenantMCPServer]:
    return list(db.execute(select(TenantMCPServer).where(TenantMCPServer.tenant_id == tenant_id).order_by(TenantMCPServer.created_at.desc())).scalars())


def create_mcp_server(db: Session, tenant_id: uuid.UUID, *, name: str, description: str | None = None, server_url: str | None = None, transport: str = "http", config: dict[str, Any] | None = None, is_enabled: bool = True) -> TenantMCPServer:
    if transport not in ALLOWED_TRANSPORTS or transport != "http":
        raise MCPError("Apenas transporte http/HTTPS está habilitado no MVP.")
    row = TenantMCPServer(tenant_id=tenant_id, name=str(name).strip()[:120], description=description, server_url=_validate_public_https_url(server_url), transport=transport, encrypted_config=_encrypt_config(config), is_enabled=is_enabled)
    db.add(row); db.commit(); db.refresh(row)
    return row


def update_mcp_server(db: Session, tenant_id: uuid.UUID, server_id: uuid.UUID, **changes: Any) -> TenantMCPServer:
    row = _server(db, tenant_id, server_id)
    if "name" in changes and changes["name"] is not None:
        row.name = str(changes["name"]).strip()[:120]
    if "description" in changes:
        row.description = changes["description"]
    if "server_url" in changes and changes["server_url"] is not None:
        row.server_url = _validate_public_https_url(changes["server_url"])
    if "is_enabled" in changes and changes["is_enabled"] is not None:
        row.is_enabled = bool(changes["is_enabled"])
    if changes.get("config") is not None:
        row.encrypted_config = _encrypt_config(changes["config"])
    db.commit(); db.refresh(row)
    return row


def delete_mcp_server(db: Session, tenant_id: uuid.UUID, server_id: uuid.UUID) -> None:
    row = _server(db, tenant_id, server_id)
    db.delete(row); db.commit()


def _headers(server: TenantMCPServer) -> dict[str, str]:
    config = _decrypt_config(server.encrypted_config)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if config.get("bearer_token"):
        headers["Authorization"] = f"Bearer {config['bearer_token']}"
    if config.get("api_key"):
        headers["X-API-Key"] = str(config["api_key"])
    return headers


def discover_mcp_tools(db: Session, tenant_id: uuid.UUID, server_id: uuid.UUID) -> list[TenantMCPTool]:
    server = _server(db, tenant_id, server_id)
    if not server.is_enabled:
        raise MCPError("Servidor MCP desabilitado.")
    started = time.monotonic()
    trace = TraceContext(tenant_id=str(tenant_id))
    record_event(db, trace, TraceEventType.MCP_DISCOVERY_STARTED, metadata={"server_id": str(server.id), "server_url": server.server_url})
    existing_tools = list(db.execute(select(TenantMCPTool).where(TenantMCPTool.tenant_id == tenant_id)).scalars())
    existing_count = len(existing_tools)
    payload = {"jsonrpc": "2.0", "id": "discover", "method": "tools/list", "params": {}}
    circuit_key = f"mcp:{tenant_id}:{server.id}"
    check_circuit(circuit_key)
    try:
        response = requests.post(str(server.server_url), headers=_headers(server), json=payload, timeout=MAX_TIMEOUT_SECONDS)
        response.raise_for_status()
        record_success(circuit_key)
        data = response.json()
    except requests.RequestException as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status is None or status >= 500 or status == 429:
            record_failure(circuit_key, reason=f"mcp_discover:{status or type(exc).__name__}")
        record_event(db, trace, TraceEventType.MCP_DISCOVERY_FINISHED, duration_ms=int((time.monotonic() - started) * 1000), metadata={"server_id": str(server.id), "status": "error", "error": type(exc).__name__})
        raise
    tools = ((data.get("result") or {}).get("tools") or data.get("tools") or []) if isinstance(data, dict) else []
    if not isinstance(tools, list):
        tools = []
    saved: list[TenantMCPTool] = []
    discovered_names: set[str] = set()
    new_count = 0
    for item in tools[:MAX_TOOLS_PER_TENANT]:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        name = str(item["name"])[:180]
        discovered_names.add(name)
        row = db.execute(select(TenantMCPTool).where(TenantMCPTool.tenant_id == tenant_id, TenantMCPTool.server_id == server.id, TenantMCPTool.tool_name == name)).scalars().first()
        if row is None:
            if existing_count + new_count >= MAX_TOOLS_PER_TENANT:
                break
            row = TenantMCPTool(tenant_id=tenant_id, server_id=server.id, tool_name=name, display_name=str(item.get("title") or name)[:180])
            db.add(row)
            new_count += 1
        elif not row.display_name:
            row.display_name = str(item.get("title") or name)[:180]
        row.description = str(item.get("description") or "")[:4000]
        row.input_schema = item.get("inputSchema") if isinstance(item.get("inputSchema"), dict) else {"type": "object"}
        row.metadata_json = sanitize_value({**(row.metadata_json or {}), "discovered": True, "last_discovered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "missing_from_last_discovery": False})
        saved.append(row)
    server_tools = [tool for tool in existing_tools if str(tool.server_id) == str(server.id)]
    for stale in server_tools:
        if stale.tool_name not in discovered_names:
            stale.metadata_json = sanitize_value({**(stale.metadata_json or {}), "missing_from_last_discovery": True, "last_missing_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())})
    db.commit()
    for row in saved: db.refresh(row)
    duration_ms = int((time.monotonic() - started) * 1000)
    record_event(db, trace, TraceEventType.MCP_DISCOVERY_FINISHED, duration_ms=duration_ms, metadata={"server_id": str(server.id), "status": "success", "tools_discovered": len(saved), "tools_new": new_count, "latency_ms": duration_ms})
    return saved


def call_mcp_tool(db: Session, tenant_id: uuid.UUID, tool_id: uuid.UUID | str, arguments: dict[str, Any] | None, timeout_seconds: int = MAX_TIMEOUT_SECONDS, budget: ExecutionBudget | None = None) -> dict[str, Any]:
    started = time.monotonic()
    trace = TraceContext(tenant_id=str(tenant_id))
    record_event(db, trace, TraceEventType.MCP_CALLED, metadata={"tool_id": str(tool_id), "arguments": arguments})
    if budget is not None:
        try:
            budget.consume_mcp_call()
        except ExecutionBudgetExceeded:
            return {"ok": False, "status": "budget_exceeded", "tool_id": str(tool_id), "latency_ms": 0, "error": "budget_exceeded", **budget.safe_metadata()}
    if str(tool_id) in CALENDAR_TOOL_IDS:
        return _call_builtin_calendar_tool(db, tenant_id, str(tool_id), arguments)
    parsed_tool_id = uuid.UUID(str(tool_id))
    tool = _tool(db, tenant_id, parsed_tool_id)
    if not tool.is_enabled:
        raise MCPError("Ferramenta MCP desabilitada.")
    server = _server(db, tenant_id, tool.server_id)
    if not server.is_enabled:
        raise MCPError("Servidor MCP desabilitado.")
    args = arguments if isinstance(arguments, dict) else {}
    try:
        validate(instance=args, schema=tool.input_schema or {"type": "object"})
    except ValidationError as exc:
        raise MCPError("Argumentos inválidos para schema da ferramenta MCP.") from exc
    timeout = min(max(int(timeout_seconds or MAX_TIMEOUT_SECONDS), 1), MAX_TIMEOUT_SECONDS)
    if budget is not None:
        remaining = budget.remaining_ms()
        if remaining <= 250:
            return {"ok": False, "status": "budget_exceeded", "tool_id": str(tool.id), "tool_name": tool.tool_name, "latency_ms": int((time.monotonic() - started) * 1000), "error": "deadline_exceeded", **budget.safe_metadata()}
        timeout = max(1, min(timeout, remaining // 1000))
    payload = {"jsonrpc": "2.0", "id": str(uuid.uuid4()), "method": "tools/call", "params": {"name": tool.tool_name, "arguments": args}}
    circuit_key = f"mcp:{tenant_id}:{server.id}"
    try:
        cb_meta = check_circuit(circuit_key)
    except CircuitBreakerOpen:
        return {"ok": False, "status": "circuit_open", "message": "Integração temporariamente indisponível.", "tool_id": str(tool.id), "tool_name": tool.tool_name, "latency_ms": int((time.monotonic() - started) * 1000), "error": "circuit_open"}
    try:
        response = requests.post(str(server.server_url), headers=_headers(server), json=payload, timeout=timeout)
        response.raise_for_status()
        record_success(circuit_key)
        raw = response.json()
        ok = not (isinstance(raw, dict) and raw.get("error"))
        result = (raw.get("result") if isinstance(raw, dict) else raw)
        out = {"ok": ok, "status": "success" if ok else "error", "tool_id": str(tool.id), "tool_name": tool.tool_name, "latency_ms": int((time.monotonic() - started) * 1000), "result": sanitize_value(result), "error": sanitize_value(raw.get("error")) if isinstance(raw, dict) else None}
        record_event(db, trace, TraceEventType.MCP_FINISHED, duration_ms=out["latency_ms"], metadata=out)
        return out
    except (requests.RequestException, ValueError, TimeoutError) as exc:
        status = getattr(getattr(exc, "response", None), "status_code", None)
        if status is None or status >= 500 or status == 429 or isinstance(exc, (requests.Timeout, requests.ConnectionError, TimeoutError)):
            record_failure(circuit_key, reason=f"mcp_call:{status or type(exc).__name__}")
        logger.warning("[MCP CALL FAILED] tenant_id=%s tool_id=%s error=%s circuit_breaker_key_hash=%s", tenant_id, tool.id, type(exc).__name__, cb_meta.get("circuit_breaker_key_hash"))
        out = {"ok": False, "status": "timeout" if "timeout" in type(exc).__name__.lower() else "error", "tool_id": str(tool.id), "tool_name": tool.tool_name, "latency_ms": int((time.monotonic() - started) * 1000), "error": type(exc).__name__}
        record_event(db, trace, TraceEventType.MCP_FINISHED, duration_ms=out["latency_ms"], metadata=out)
        return out
