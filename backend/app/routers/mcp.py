from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.tenant import Tenant
from app.models.tenant_mcp import TenantMCPTool
from app.services.google_calendar_service import PROVIDER as GOOGLE_CALENDAR_PROVIDER
from app.services.gmail_service import PROVIDER as GMAIL_PROVIDER
from app.services.google_drive_service import PROVIDER as GOOGLE_DRIVE_PROVIDER
from app.services.integration_connection_service import IntegrationConnectionService
from app.services.mcp_service import MCPError, call_mcp_tool, create_mcp_server, delete_mcp_server, discover_mcp_tools, list_mcp_servers, update_mcp_server
from app.tools.adapters.google_calendar_tool_adapter import google_calendar_tool_definitions
from app.tools.adapters.gmail_tool_adapter import gmail_tool_definitions
from app.tools.adapters.google_drive_tool_adapter import google_drive_tool_definitions
from app.services.tenant_service import get_current_tenant

router = APIRouter(prefix="/api/mcp", tags=["mcp"])


class MCPServerIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    server_url: str
    transport: str = "http"
    config: dict[str, Any] | None = None
    is_enabled: bool = True


class MCPServerPatch(BaseModel):
    name: str | None = Field(default=None, max_length=120)
    description: str | None = None
    server_url: str | None = None
    config: dict[str, Any] | None = None
    is_enabled: bool | None = None


class MCPToolPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=180)
    description: str | None = None
    is_enabled: bool | None = None
    metadata: dict[str, Any] | None = None


class MCPToolTest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: int = 15


def _server_out(row) -> dict[str, Any]:
    return {"id": str(row.id), "tenant_id": str(row.tenant_id), "name": row.name, "description": row.description, "server_url": row.server_url, "transport": row.transport, "is_enabled": row.is_enabled, "has_config": bool(row.encrypted_config), "created_at": row.created_at, "updated_at": row.updated_at}


def _tool_out(row: TenantMCPTool) -> dict[str, Any]:
    return {"id": str(row.id), "tenant_id": str(row.tenant_id), "server_id": str(row.server_id), "tool_name": row.tool_name, "display_name": row.display_name, "description": row.description, "input_schema": row.input_schema, "is_enabled": row.is_enabled, "metadata": row.metadata_json or {}, "created_at": row.created_at, "updated_at": row.updated_at}


def _google_calendar_tools_out(db: Session, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    connected = IntegrationConnectionService(db).get_active_connection(tenant_id, GOOGLE_CALENDAR_PROVIDER) is not None
    if not connected:
        return []
    return [{**tool, "tenant_id": str(tenant_id)} for tool in google_calendar_tool_definitions(connected=True)]



def _google_drive_tools_out(db: Session, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    connected = IntegrationConnectionService(db).get_active_connection(tenant_id, GOOGLE_DRIVE_PROVIDER) is not None
    if not connected:
        return []
    return [{**tool, "tenant_id": str(tenant_id)} for tool in google_drive_tool_definitions(connected=True)]

def _gmail_tools_out(db: Session, tenant_id: uuid.UUID) -> list[dict[str, Any]]:
    connected = IntegrationConnectionService(db).get_active_connection(tenant_id, GMAIL_PROVIDER) is not None
    if not connected:
        return []
    return [{**tool, "tenant_id": str(tenant_id)} for tool in gmail_tool_definitions(connected=True)]


def _mcp_error(exc: MCPError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/servers")
def get_servers(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    return [_server_out(row) for row in list_mcp_servers(db, tenant.id)]


@router.post("/servers", status_code=201)
def create_server(payload: MCPServerIn, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    server = None
    try:
        server = create_mcp_server(db, tenant.id, **payload.model_dump())
        tools = discover_mcp_tools(db, tenant.id, server.id)
        return {**_server_out(server), "discovery": {"status": "success", "tools_discovered": len(tools)}}
    except MCPError as exc:
        if server is not None:
            delete_mcp_server(db, tenant.id, server.id)
        raise _mcp_error(exc) from exc
    except Exception as exc:
        if server is not None:
            delete_mcp_server(db, tenant.id, server.id)
        raise HTTPException(status_code=502, detail="Falha controlada ao descobrir ferramentas MCP; integração não foi cadastrada.") from exc


@router.put("/servers/{server_id}")
def patch_server(server_id: uuid.UUID, payload: MCPServerPatch, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    try:
        return _server_out(update_mcp_server(db, tenant.id, server_id, **payload.model_dump(exclude_unset=True)))
    except MCPError as exc:
        raise _mcp_error(exc) from exc


@router.delete("/servers/{server_id}", status_code=204)
def remove_server(server_id: uuid.UUID, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    try:
        delete_mcp_server(db, tenant.id, server_id)
    except MCPError as exc:
        raise _mcp_error(exc) from exc


@router.post("/servers/{server_id}/discover")
def discover(server_id: uuid.UUID, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    try:
        return [_tool_out(row) for row in discover_mcp_tools(db, tenant.id, server_id)]
    except MCPError as exc:
        raise _mcp_error(exc) from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Falha controlada ao descobrir ferramentas MCP.") from exc


@router.get("/tools")
def get_tools(tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    rows = db.execute(select(TenantMCPTool).where(TenantMCPTool.tenant_id == tenant.id).order_by(TenantMCPTool.created_at.desc())).scalars().all()
    return [*_google_calendar_tools_out(db, tenant.id), *_gmail_tools_out(db, tenant.id), *_google_drive_tools_out(db, tenant.id), *[_tool_out(row) for row in rows]]


@router.put("/tools/{tool_id}")
def patch_tool(tool_id: uuid.UUID, payload: MCPToolPatch, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    row = db.execute(select(TenantMCPTool).where(TenantMCPTool.tenant_id == tenant.id, TenantMCPTool.id == tool_id)).scalars().first()
    if not row:
        raise HTTPException(status_code=404, detail="Ferramenta MCP não encontrada.")
    changes = payload.model_dump(exclude_unset=True)
    for field in ("display_name", "description", "is_enabled", "metadata"):
        if field in changes:
            setattr(row, "metadata_json" if field == "metadata" else field, changes[field])
    db.commit(); db.refresh(row)
    return _tool_out(row)


@router.post("/tools/{tool_id}/test")
def test_tool(tool_id: uuid.UUID, payload: MCPToolTest, tenant: Tenant = Depends(get_current_tenant), db: Session = Depends(get_db)):
    try:
        return call_mcp_tool(db, tenant.id, tool_id, payload.input, payload.timeout_seconds)
    except MCPError as exc:
        raise _mcp_error(exc) from exc
