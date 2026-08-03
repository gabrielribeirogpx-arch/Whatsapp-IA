from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.integration_connection import IntegrationConnection
from app.models.tenant_mcp import TenantMCPServer, TenantMCPTool
from app.tools.adapters.google_calendar_tool_adapter import google_calendar_tool_definitions


INTERNAL_PROVIDERS = {"google_calendar": google_calendar_tool_definitions}


def _integration_status(connection: IntegrationConnection) -> str:
    if connection.status != "active":
        return "disconnected"
    # An expired access token is still usable when OAuth supplied a refresh token.
    if connection.expires_at and connection.expires_at <= datetime.utcnow() and not connection.refresh_token_encrypted:
        return "expired"
    return "connected"


def list_executable_connections(db: Session, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    """Return safe, tenant-scoped handles; credentials never leave their source rows."""
    integrations = db.execute(
        select(IntegrationConnection).where(
            IntegrationConnection.tenant_id == tenant_id,
            IntegrationConnection.provider.in_(tuple(INTERNAL_PROVIDERS)),
        )
    ).scalars().all()
    servers = db.execute(
        select(TenantMCPServer).where(TenantMCPServer.tenant_id == tenant_id)
    ).scalars().all()
    result: list[dict[str, Any]] = []
    for connection in integrations:
        metadata = connection.metadata_json if isinstance(connection.metadata_json, dict) else {}
        account = metadata.get("account_email") or metadata.get("email")
        status = _integration_status(connection)
        name = f"Google Calendar — {account}" if account else (
            "Google Calendar — Reconectar conta" if status != "connected" else "Google Calendar"
        )
        result.append({
            "id": f"integration:{connection.id}", "name": name,
            "provider": connection.provider, "connection_kind": "internal_integration",
            "status": status, "supports_mcp_tools": True,
        })
    result.extend({
        "id": f"mcp:{server.id}", "name": server.name, "provider": "mcp",
        "connection_kind": "external_mcp",
        "status": "connected" if server.is_enabled else "disconnected",
        "supports_mcp_tools": True,
    } for server in servers)
    return result


def list_connection_tools(db: Session, tenant_id: uuid.UUID, connection_id: str) -> list[dict[str, Any]]:
    kind, separator, raw_id = connection_id.partition(":")
    if not separator:
        kind, raw_id = "mcp", connection_id  # backwards-compatible snapshots
    try:
        parsed_id = uuid.UUID(raw_id)
    except ValueError:
        return []
    if kind == "integration":
        connection = db.execute(select(IntegrationConnection).where(
            IntegrationConnection.id == parsed_id,
            IntegrationConnection.tenant_id == tenant_id,
        )).scalars().first()
        if not connection or connection.provider not in INTERNAL_PROVIDERS:
            return []
        connected = _integration_status(connection) == "connected"
        metadata = connection.metadata_json if isinstance(connection.metadata_json, dict) else {}
        account = metadata.get("account_email") or metadata.get("email")
        name = f"Google Calendar — {account}" if account else ("Google Calendar" if connected else "Google Calendar — Reconectar conta")
        return [{**tool, "server_id": connection_id, "connection_id": connection_id, "server_name": name,
                 "connection_status": _integration_status(connection)}
                for tool in INTERNAL_PROVIDERS[connection.provider](connected=connected)]
    if kind == "mcp":
        server = db.execute(select(TenantMCPServer).where(
            TenantMCPServer.id == parsed_id, TenantMCPServer.tenant_id == tenant_id,
        )).scalars().first()
        if not server:
            return []
        tools = db.execute(select(TenantMCPTool).where(
            TenantMCPTool.server_id == server.id, TenantMCPTool.tenant_id == tenant_id,
        )).scalars().all()
        return [{"id": str(tool.id), "server_id": connection_id, "connection_id": connection_id,
                 "tool_name": tool.tool_name, "display_name": tool.display_name,
                 "description": tool.description, "input_schema": tool.input_schema,
                 "is_enabled": tool.is_enabled, "server_name": server.name,
                 "metadata": tool.metadata_json or {}} for tool in tools]
    return []
