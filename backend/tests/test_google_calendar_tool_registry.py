from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.models.integration_connection import IntegrationConnection
from app.models.tenant_mcp import TenantMCPTool
from app.routers.mcp import router
from app.services.integration_connection_service import IntegrationConnectionService
from app.services.tenant_service import get_current_tenant
from app.tools import ToolContext, ToolRegistry
from app.tools.adapters.google_calendar_tool_adapter import GoogleCalendarToolAdapter, google_calendar_tool_definitions


class _ScalarResult:
    def __init__(self, rows):
        self._rows = rows
    def first(self):
        return self._rows[0] if self._rows else None
    def all(self):
        return self._rows


class _ExecuteResult:
    def __init__(self, rows):
        self._rows = rows
    def scalars(self):
        return _ScalarResult(self._rows)


class FakeDb:
    def __init__(self):
        self.connections = []
        self.mcp_tools = []
    def execute(self, statement):
        compiled = statement.compile()
        params = compiled.params
        text = str(compiled)
        rows = self.mcp_tools if "tenant_mcp_tools" in text else self.connections
        tenant_id = params.get("tenant_id_1")
        provider = params.get("provider_1")
        if tenant_id is not None:
            rows = [row for row in rows if row.tenant_id == tenant_id]
        if provider is not None:
            rows = [row for row in rows if getattr(row, "provider", None) == provider]
        return _ExecuteResult(rows)


def _client(db, tenant_id):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_tenant] = lambda: SimpleNamespace(id=tenant_id)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app)


def test_connected_tenant_sees_real_google_calendar_tools_and_mcp_stays_separate(monkeypatch):
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", "integration-test-secret")
    tenant_id = uuid.uuid4()
    db = FakeDb()
    db.connections.append(IntegrationConnection(tenant_id=tenant_id, provider="google_calendar", auth_type="oauth2", status="active"))
    db.mcp_tools.append(TenantMCPTool(id=uuid.uuid4(), tenant_id=tenant_id, server_id=uuid.uuid4(), tool_name="calendar_create_event", display_name="calendar_create_event", description="fake", is_enabled=True))

    payload = _client(db, tenant_id).get("/api/mcp/tools").json()

    google_tool = next(item for item in payload if item["id"] == "google_calendar_create_event")
    assert google_tool["display_name"] == "[Google Calendar] Criar evento"
    assert google_tool["server_name"] == "Google Calendar conectado"
    assert google_tool["metadata"]["kind"] == "internal"
    assert google_tool["input_schema"]["required"] == ["start", "end"]
    assert set(google_tool["input_schema"]["properties"]) == {"title", "summary", "start", "end", "timezone", "description", "location", "attendees"}
    assert google_tool["input_schema"]["properties"]["start"]["format"] == "date-time"
    assert "{{selected_slot.start}}" in google_tool["input_schema"]["properties"]["start"]["description"]
    assert "{{selected_slot.end}}" in google_tool["input_schema"]["properties"]["end"]["description"]
    assert "{{selected_slot.timezone}}" in google_tool["input_schema"]["properties"]["timezone"]["description"]
    assert any(item["tool_name"] == "calendar_create_event" and item["id"] != "google_calendar_create_event" for item in payload)


def test_unconnected_tenant_does_not_see_google_calendar_tools(monkeypatch):
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", "integration-test-secret")
    tenant_id = uuid.uuid4()
    payload = _client(FakeDb(), tenant_id).get("/api/mcp/tools").json()
    assert all(not str(item["id"]).startswith("google_calendar_") for item in payload)


def test_tool_registry_executes_real_google_calendar_with_current_tenant():
    tenant_id = uuid.uuid4()
    calls = []

    class FakeService:
        def __init__(self, db, service_tenant_id):
            calls.append((db, service_tenant_id))
        def list_events(self, **kwargs):
            return {"ok": True, "events": [{"event_id": "evt-1"}], "kwargs": kwargs}

    registry = ToolRegistry()
    db = object()
    registry.register(GoogleCalendarToolAdapter(db, service_factory=FakeService))

    result = registry.execute("google_calendar", "google_calendar_list_events", {"max_results": 1}, ToolContext(tenant_id=tenant_id))

    assert result.ok is True
    assert calls == [(db, tenant_id)]
    assert result.normalized_result is not None
    assert result.normalized_result.type == "google_calendar.list_events"


def test_create_event_and_availability_definitions_receive_their_own_schemas():
    definitions = google_calendar_tool_definitions(connected=True)
    create = next(item for item in definitions if item["id"] == "google_calendar_create_event")
    availability_tools = [
        next(item for item in definitions if item["id"] == tool_id)
        for tool_id in ("google_calendar_check_availability", "calendar.get_availability")
    ]

    assert create["input_schema"]["properties"]
    assert create["input_schema"]["required"] == ["start", "end"]
    assert "title" in create["input_schema"]["properties"]
    for availability in availability_tools:
        assert set(availability["input_schema"]["properties"]) == {"start", "end", "timezone", "mode"}
        assert availability["input_schema"]["required"] == ["start", "end"]
    assert availability_tools[0]["input_schema"] == availability_tools[1]["input_schema"]
    assert create["input_schema"] != availability_tools[0]["input_schema"]


def test_create_event_rejects_empty_arguments_without_calling_service():
    class FakeService:
        def __init__(self, db, tenant_id):
            raise AssertionError("invalid input must not reach the service")

    registry = ToolRegistry()
    registry.register(GoogleCalendarToolAdapter(object(), service_factory=FakeService))
    result = registry.execute("google_calendar", "google_calendar_create_event", {}, ToolContext(tenant_id=uuid.uuid4()))

    assert result.ok is False
    assert result.error_code == "google_calendar_invalid_arguments"
    assert result.structured_content["error"] == "google_calendar_invalid_arguments"


def test_create_event_forwards_rendered_slot_arguments_unchanged():
    calls = []

    class FakeService:
        def __init__(self, db, tenant_id):
            pass

        def create_event(self, **kwargs):
            calls.append(kwargs)
            return {"ok": True, "event_id": "evt-1", "title": kwargs.get("title"), "start": kwargs["start"], "end": kwargs["end"]}

    arguments = {
        "title": "Consulta",
        "start": "2026-09-01T10:00:00-03:00",
        "end": "2026-09-01T11:00:00-03:00",
        "timezone": "America/Sao_Paulo",
    }
    registry = ToolRegistry()
    registry.register(GoogleCalendarToolAdapter(object(), service_factory=FakeService))
    result = registry.execute("google_calendar", "google_calendar_create_event", arguments, ToolContext(tenant_id=uuid.uuid4()))

    assert result.ok is True
    assert calls == [arguments]


def test_update_event_definition_publishes_canonical_write_schema():
    update = next(
        item for item in google_calendar_tool_definitions(connected=True)
        if item["id"] == "google_calendar_update_event"
    )

    assert update["display_name"] == "[Google Calendar] Atualizar evento"
    assert update["metadata"]["classification"] == "WRITE"
    assert set(update["input_schema"]["properties"]) == {
        "event_id", "start", "end", "timezone", "title", "description",
    }
    assert update["input_schema"]["required"] == ["event_id", "start", "end"]
    assert update["input_schema"]["properties"]["start"]["format"] == "date-time"
    assert update["input_schema"]["properties"]["end"]["format"] == "date-time"


@pytest.mark.parametrize("missing", ["event_id", "start", "end"])
def test_update_event_rejects_each_missing_required_argument_without_calling_service(missing):
    class FakeService:
        def __init__(self, db, tenant_id):
            raise AssertionError("invalid input must not reach the service")

    arguments = {
        "event_id": "evt-1",
        "start": "2026-09-10T10:00:00-03:00",
        "end": "2026-09-10T11:00:00-03:00",
    }
    arguments.pop(missing)
    registry = ToolRegistry()
    registry.register(GoogleCalendarToolAdapter(object(), service_factory=FakeService))

    result = registry.execute(
        "google_calendar", "google_calendar_update_event", arguments,
        ToolContext(tenant_id=uuid.uuid4()),
    )

    assert result.ok is False
    assert result.error_code == "google_calendar_invalid_arguments"
    assert result.structured_content["error"] == "google_calendar_invalid_arguments"


def test_update_event_calls_existing_event_and_returns_canonical_success():
    calls = []

    class FakeService:
        def __init__(self, db, tenant_id):
            pass

        def update_event(self, event_id, **kwargs):
            calls.append((event_id, kwargs))
            return {"ok": True, "event_id": event_id, **kwargs}

        def create_event(self, **kwargs):
            raise AssertionError("update must never create an event")

    arguments = {
        "event_id": "evt-existing",
        "start": "2026-09-10T10:00:00-03:00",
        "end": "2026-09-10T11:00:00-03:00",
        "timezone": "America/Sao_Paulo",
        "title": "Consulta - Ana",
    }
    registry = ToolRegistry()
    registry.register(GoogleCalendarToolAdapter(object(), service_factory=FakeService))

    result = registry.execute(
        "google_calendar", "google_calendar_update_event", arguments,
        ToolContext(tenant_id=uuid.uuid4()),
    )

    assert result.ok is True
    assert calls == [("evt-existing", {key: value for key, value in arguments.items() if key != "event_id"})]
    assert result.output["timezone"] == "America/Sao_Paulo"
    assert result.normalized_result.type == "google_calendar.update_event"


def test_update_event_returns_structured_error_from_service_failure():
    class FakeService:
        def __init__(self, db, tenant_id):
            pass

        def update_event(self, event_id, **kwargs):
            return {"ok": False, "message": "calendar_update_failed", "status_code": 404}

    registry = ToolRegistry()
    registry.register(GoogleCalendarToolAdapter(object(), service_factory=FakeService))
    result = registry.execute("google_calendar", "google_calendar_update_event", {
        "event_id": "missing", "start": "2026-09-10T10:00:00Z", "end": "2026-09-10T11:00:00Z",
    }, ToolContext(tenant_id=uuid.uuid4()))

    assert result.ok is False
    assert result.error_code == "google_calendar_error"
    assert result.structured_content == {
        "ok": False, "tool": "google_calendar_update_event", "result": {}, "error": "calendar_update_failed",
    }
