"""Deterministic MCP tool node for Runtime V2."""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass
from typing import Any

from jsonschema import ValidationError, validate
from sqlalchemy import select

from app.flow_v2.contracts import FlowV2EventType
from app.flow_v2.executors.base_executor import BaseNodeExecutor, NodeExecutionResult
from app.models.tenant_mcp import TenantMCPServer, TenantMCPTool
from app.models.integration_connection import IntegrationConnection
from app.tools.adapters.google_calendar_tool_adapter import GoogleCalendarToolAdapter, GOOGLE_CALENDAR_TOOL_IDS, google_calendar_tool_definitions
from app.tools.context import ToolContext
from app.services.mcp_service import MCPError, call_mcp_tool

logger = logging.getLogger(__name__)
MAX_RESPONSE_BYTES = 512_000


@dataclass(frozen=True)
class MCPNodeError(Exception):
    code: str
    message: str
    retryable: bool = False

    def safe_value(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "retryable": self.retryable}


def normalize_mcp_response(response: Any) -> dict[str, Any]:
    if not isinstance(response, dict):
        raise MCPNodeError("MCP_INVALID_RESPONSE", "O servidor MCP retornou uma resposta inválida.")
    result = response.get("result")
    result = result if isinstance(result, dict) else {}
    content = result.get("content") if isinstance(result.get("content"), list) else []
    structured = result.get("structuredContent", result.get("structured_content"))
    if not isinstance(structured, (dict, list)):
        structured = None
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text" and isinstance(item.get("text"), str):
                try:
                    candidate = json.loads(item["text"])
                    if isinstance(candidate, (dict, list)):
                        structured = candidate
                        break
                except (ValueError, TypeError):
                    pass
    is_error = response.get("ok") is not True or bool(result.get("isError", result.get("is_error", False)))
    return {"ok": not is_error, "content": content, "structured_content": structured, "is_error": is_error}


def safe_get_path(value: Any, path: str | None) -> Any:
    current = value
    for part in [item for item in str(path or "").split(".") if item]:
        if part.startswith("__") or not isinstance(current, dict) or part not in current:
            raise MCPNodeError("MCP_INVALID_RESPONSE", "O caminho configurado não existe na resposta MCP.")
        current = current[part]
    return current


class MCPToolNodeExecutor(BaseNodeExecutor):
    """Executes exactly one tenant-authorized tool and selects one branch."""

    def execute(self, db, *, snapshot, session, node, runtime_input) -> NodeExecutionResult:
        data = self._node_data(node)
        node_id = str(node.get("id") or "")
        started = time.monotonic()
        handle = "error"
        attempt = 0
        tool_name = str(data.get("tool_name") or "")
        timeout = min(max(int(data.get("timeout_seconds") or 30), 1), 60)
        retry = data.get("retry") if isinstance(data.get("retry"), dict) else {}
        max_attempts = min(max(int(retry.get("max_attempts") or 1), 1), 5) if retry.get("enabled") else 1
        try:
            connection_id = str(data.get("connection_id") or "")
            if not connection_id:
                raise MCPNodeError("MCP_CONNECTION_NOT_FOUND", "A conexão MCP não foi encontrada.")
            connection_kind, separator, raw_connection_id = connection_id.partition(":")
            if not separator:
                connection_kind, raw_connection_id = "mcp", connection_id
            try:
                parsed_connection_id = uuid.UUID(raw_connection_id)
            except ValueError as exc:
                raise MCPNodeError("MCP_CONNECTION_NOT_FOUND", "A conexão MCP não foi encontrada.") from exc
            if connection_kind == "integration":
                integration = db.execute(select(IntegrationConnection).where(
                    IntegrationConnection.id == parsed_connection_id,
                    IntegrationConnection.tenant_id == session.tenant_id,
                    IntegrationConnection.provider == "google_calendar",
                    IntegrationConnection.status == "active",
                )).scalars().first()
                if integration is None:
                    raise MCPNodeError("MCP_CONNECTION_UNAUTHORIZED", "A integração não está autorizada para este workspace.")
                if tool_name not in GOOGLE_CALENDAR_TOOL_IDS:
                    raise MCPNodeError("MCP_TOOL_NOT_FOUND", "A ferramenta não está disponível nesta integração.")
                definitions = {item["tool_name"]: item for item in google_calendar_tool_definitions(connected=True)}
                tool_definition = definitions[tool_name]
                classification = str(tool_definition["metadata"].get("classification") or "READ").upper()
                if classification in {"WRITE", "DESTRUCTIVE"} and data.get("allow_external_write") is not True:
                    raise MCPNodeError("MCP_CONNECTION_UNAUTHORIZED", "Esta ação exige confirmação explícita para alterar dados externos.")
                if classification == "DESTRUCTIVE" and data.get("destructive_confirmed") is not True:
                    raise MCPNodeError("MCP_CONNECTION_UNAUTHORIZED", "A ação destrutiva exige confirmação explícita.")
                arguments = self._render(data.get("arguments") or {}, db, snapshot=snapshot, session=session, runtime_input=runtime_input, node_id=node_id)
                if not isinstance(arguments, dict):
                    raise MCPNodeError("MCP_ARGUMENT_VALIDATION_FAILED", "Os argumentos MCP devem formar um objeto JSON.")
                try:
                    validate(arguments, tool_definition.get("input_schema") or {"type": "object"})
                except ValidationError as exc:
                    raise MCPNodeError("MCP_ARGUMENT_VALIDATION_FAILED", "Os argumentos não correspondem ao schema da ferramenta.") from exc
                result = GoogleCalendarToolAdapter(db).execute(tool_name, arguments, ToolContext(tenant_id=session.tenant_id))
                if not result.ok:
                    raise MCPNodeError(result.error_code or "MCP_TOOL_EXECUTION_FAILED", "A integração não concluiu a execução.", True)
                output = result.structured_content if result.structured_content is not None else result.output
                output = safe_get_path(output, data.get("result_path")) if data.get("result_path") else output
                variables = dict(getattr(session, "variables", None) or {})
                variables[str(data["output_variable"])] = output
                session.variables = variables
                db.add(session); db.flush()
                handle = "success"
                raise StopIteration
            if connection_kind != "mcp":
                raise MCPNodeError("MCP_CONNECTION_NOT_FOUND", "A conexão MCP não foi encontrada.")
            server = db.execute(select(TenantMCPServer).where(TenantMCPServer.id == parsed_connection_id, TenantMCPServer.tenant_id == session.tenant_id)).scalars().first()
            if server is None or not server.is_enabled:
                raise MCPNodeError("MCP_CONNECTION_UNAUTHORIZED", "A conexão MCP não está autorizada para este workspace.")
            tool = db.execute(select(TenantMCPTool).where(TenantMCPTool.server_id == server.id, TenantMCPTool.tenant_id == session.tenant_id, TenantMCPTool.tool_name == tool_name, TenantMCPTool.is_enabled.is_(True))).scalars().first()
            if tool is None:
                raise MCPNodeError("MCP_TOOL_NOT_FOUND", "A ferramenta MCP não está autorizada nesta conexão.")
            classification = str((tool.metadata_json or {}).get("classification") or "READ").upper()
            if classification in {"WRITE", "DESTRUCTIVE"} and data.get("allow_external_write") is not True:
                raise MCPNodeError("MCP_CONNECTION_UNAUTHORIZED", "Este node não permite alterações em dados externos.")
            if classification == "DESTRUCTIVE" and (data.get("destructive_confirmed") is not True or not data.get("idempotency_key")):
                raise MCPNodeError("MCP_CONNECTION_UNAUTHORIZED", "A ação destrutiva exige confirmação e idempotência.")
            arguments = self._render(data.get("arguments") or {}, db, snapshot=snapshot, session=session, runtime_input=runtime_input, node_id=node_id)
            if not isinstance(arguments, dict):
                raise MCPNodeError("MCP_ARGUMENT_VALIDATION_FAILED", "Os argumentos MCP devem formar um objeto JSON.")
            schema_properties = (tool.input_schema or {}).get("properties") or {}
            if data.get("idempotency_key") and "idempotency_key" in schema_properties:
                arguments["idempotency_key"] = self._render(data["idempotency_key"], db, snapshot=snapshot, session=session, runtime_input=runtime_input, node_id=node_id)
            try:
                validate(arguments, tool.input_schema or {"type": "object"})
            except ValidationError as exc:
                raise MCPNodeError("MCP_ARGUMENT_VALIDATION_FAILED", "Os argumentos não correspondem ao schema da ferramenta.") from exc
            for attempt in range(1, max_attempts + 1):
                logger.info("event=RUNTIME_V2_MCP_TOOL_START tenant_id=%s flow_id=%s session_id=%s node_id=%s connection_id=%s server_name=%s tool_name=%s attempt=%s timeout_seconds=%s", session.tenant_id, getattr(snapshot, "flow_id", None), session.id, node_id, server.id, server.name, tool.tool_name, attempt, timeout)
                response = call_mcp_tool(db, session.tenant_id, tool.id, arguments, timeout_seconds=timeout)
                if response.get("status") == "timeout":
                    if attempt < max_attempts:
                        time.sleep(min(max(int(retry.get("backoff_ms") or 1000), 0), 10_000) / 1000)
                        continue
                    raise MCPNodeError("MCP_TIMEOUT", "A ferramenta não respondeu no tempo limite.", True)
                normalized = normalize_mcp_response(response)
                if normalized["is_error"]:
                    if attempt < max_attempts:
                        time.sleep(min(max(int(retry.get("backoff_ms") or 1000), 0), 10_000) / 1000)
                        continue
                    raise MCPNodeError("MCP_TOOL_EXECUTION_FAILED", "A ferramenta MCP não concluiu a execução.", True)
                encoded = json.dumps(normalized, ensure_ascii=False, default=str).encode()
                if len(encoded) > MAX_RESPONSE_BYTES:
                    raise MCPNodeError("MCP_INVALID_RESPONSE", "A resposta MCP excedeu o limite permitido.")
                preferred = normalized["structured_content"] if normalized["structured_content"] is not None else normalized["content"]
                output = safe_get_path(preferred, data.get("result_path")) if data.get("result_path") else preferred
                variables = dict(getattr(session, "variables", None) or {})
                variables[str(data["output_variable"])] = output
                if data.get("save_raw_response") is True:
                    variables[str(data.get("raw_response_variable") or "mcp_raw_response")] = normalized
                variables.pop(str(data.get("error_variable") or "mcp_error"), None)
                session.variables = variables
                db.add(session); db.flush()
                handle = "success"
                break
        except StopIteration:
            pass
        except MCPNodeError as exc:
            handle = "timeout" if exc.code == "MCP_TIMEOUT" else "error"
            variables = dict(getattr(session, "variables", None) or {})
            variables[str(data.get("error_variable") or "mcp_error")] = exc.safe_value()
            session.variables = variables
            db.add(session); db.flush()
            logger.info("event=RUNTIME_V2_MCP_TOOL_ERROR session_id=%s node_id=%s tool_name=%s error_code=%s retryable=%s attempt=%s source_handle=%s", session.id, node_id, tool_name, exc.code, exc.retryable, attempt, handle)
        except (MCPError, ValueError, TypeError) as exc:
            variables = dict(getattr(session, "variables", None) or {})
            variables[str(data.get("error_variable") or "mcp_error")] = {"code": "MCP_TOOL_EXECUTION_FAILED", "message": "Não foi possível executar a ferramenta MCP.", "retryable": False}
            session.variables = variables
            db.add(session); db.flush()
            logger.info("event=RUNTIME_V2_MCP_TOOL_ERROR session_id=%s node_id=%s tool_name=%s error_code=MCP_TOOL_EXECUTION_FAILED retryable=false attempt=%s source_handle=error", session.id, node_id, tool_name, attempt)
        resolution = self.transition_resolver.resolve(db, snapshot=snapshot, session=session, source_node_id=node_id, source_handle=handle)
        next_id = resolution.target_node_id
        duration = int((time.monotonic() - started) * 1000)
        logger.info("event=RUNTIME_V2_MCP_TOOL_RESULT session_id=%s node_id=%s tool_name=%s duration_ms=%s success=%s output_variable=%s source_handle=%s", session.id, node_id, tool_name, duration, handle == "success", data.get("output_variable"), handle)
        self.event_store.append(db, session=session, event_type=FlowV2EventType.OUTPUT_EMITTED, node_id=node_id, payload={"source_handle": handle, "duration_ms": duration, "attempts": attempt})
        return NodeExecutionResult(next_node_id=next_id, status="continue" if next_id else "complete", next_source_handle=handle)
