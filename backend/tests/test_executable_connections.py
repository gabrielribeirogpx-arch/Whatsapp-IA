import uuid
from datetime import datetime, timedelta

from app.models.integration_connection import IntegrationConnection
from app.models.tenant_mcp import TenantMCPServer, TenantMCPTool
from app.services.executable_connection_service import list_connection_tools, list_executable_connections


class Result:
    def __init__(self, rows): self.rows = rows
    def scalars(self): return self
    def all(self): return self.rows
    def first(self): return self.rows[0] if self.rows else None


class DB:
    def __init__(self, integration=None, servers=None, tools=None):
        self.integration, self.servers, self.tools = integration, servers or [], tools or []
        self.queries = []
    def execute(self, query):
        sql = str(query); self.queries.append(sql)
        if "integration_connections" in sql: return Result([self.integration] if self.integration else [])
        if "tenant_mcp_tools" in sql: return Result(self.tools)
        return Result(self.servers)


def test_connected_calendar_and_external_mcp_are_unified_without_credentials():
    tenant_id = uuid.uuid4()
    connection = IntegrationConnection(id=uuid.uuid4(), tenant_id=tenant_id, provider="google_calendar", auth_type="oauth2", status="active", access_token_encrypted="secret", refresh_token_encrypted="refresh", metadata_json={"account_email": "conta@gmail.com"})
    server = TenantMCPServer(id=uuid.uuid4(), tenant_id=tenant_id, name="Servidor externo", server_url="https://example.test", transport="http", is_enabled=True)
    payload = list_executable_connections(DB(connection, [server]), tenant_id)
    assert {item["connection_kind"] for item in payload} == {"internal_integration", "external_mcp"}
    assert payload[0]["id"] == f"integration:{connection.id}"
    assert payload[0]["name"] == "Google Calendar — conta@gmail.com"
    assert "secret" not in str(payload) and "token" not in str(payload).lower()


def test_expired_calendar_without_refresh_is_signalled():
    tenant_id = uuid.uuid4()
    connection = IntegrationConnection(id=uuid.uuid4(), tenant_id=tenant_id, provider="google_calendar", auth_type="oauth2", status="active", expires_at=datetime.utcnow() - timedelta(minutes=1), metadata_json={})
    payload = list_executable_connections(DB(connection), tenant_id)
    assert payload[0]["status"] == "expired"
    assert "Reconectar" in payload[0]["name"]


def test_calendar_tools_list_uses_safe_connection_handle_and_deterministic_names():
    tenant_id = uuid.uuid4()
    connection = IntegrationConnection(id=uuid.uuid4(), tenant_id=tenant_id, provider="google_calendar", auth_type="oauth2", status="active", refresh_token_encrypted="encrypted", metadata_json={})
    db = DB(connection)
    payload = list_connection_tools(db, tenant_id, f"integration:{connection.id}")
    assert {"calendar.get_availability", "calendar.create_appointment", "calendar.get_appointment", "calendar.reschedule_appointment", "calendar.cancel_appointment"} <= {item["tool_name"] for item in payload}
    assert all(item["server_id"] == f"integration:{connection.id}" for item in payload)
    assert all("tenant_id" in query for query in db.queries)
