from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.external_identity import APPOINTMENT_PATIENT, derive_external_reference, is_valid_external_reference
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


def _execute_identified_create(monkeypatch, *, tenant_id, contact_id, arguments=None):
    monkeypatch.setenv("EXTERNAL_IDENTITY_SECRET", "s" * 32)
    calls = []

    class FakeService:
        def __init__(self, db, service_tenant_id):
            assert service_tenant_id == tenant_id

        def create_event(self, **kwargs):
            calls.append(kwargs)
            return {
                "ok": True,
                "event_id": "evt-1",
                "title": kwargs.get("title"),
                "start": kwargs["start"],
                "end": kwargs["end"],
            }

    payload = {
        "title": "Consulta de Maria",
        "description": "Retorno da paciente",
        "location": "Sala 2",
        "attendees": ["medico@example.com"],
        "start": "2026-12-01T10:00:00-03:00",
        "end": "2026-12-01T11:00:00-03:00",
        "timezone": "America/Sao_Paulo",
        **(arguments or {}),
    }
    result = GoogleCalendarToolAdapter(object(), service_factory=FakeService).execute(
        "google_calendar_create_event",
        payload,
        ToolContext(tenant_id=tenant_id, contact_id=contact_id),
    )
    return result, calls


def test_identified_create_uses_exact_trusted_patient_reference_and_preserves_fields(monkeypatch):
    tenant_id = uuid.uuid4()
    contact_id = uuid.uuid4()
    result, calls = _execute_identified_create(
        monkeypatch, tenant_id=tenant_id, contact_id=contact_id,
    )

    assert result.ok is True
    assert len(calls) == 1
    metadata = calls[0].pop("asa_private_metadata")
    assert metadata == {
        "asa_managed": "true",
        "asa_schema": "appointment-v1",
        "asa_patient_ref": derive_external_reference(
            tenant_id=tenant_id,
            subject_id=contact_id,
            purpose=APPOINTMENT_PATIENT,
        ),
    }
    assert is_valid_external_reference(metadata["asa_patient_ref"])
    assert calls[0] == {
        "title": "Consulta de Maria",
        "description": "Retorno da paciente",
        "location": "Sala 2",
        "attendees": ["medico@example.com"],
        "start": "2026-12-01T10:00:00-03:00",
        "end": "2026-12-01T11:00:00-03:00",
        "timezone": "America/Sao_Paulo",
    }
    assert "asa_patient_ref" not in result.output


def test_identified_create_isolates_tenants_contacts_and_ignores_spoofed_arguments(monkeypatch):
    tenant_a, tenant_b = uuid.uuid4(), uuid.uuid4()
    contact_a, contact_b = uuid.uuid4(), uuid.uuid4()
    spoof = {
        "tenant_id": str(uuid.uuid4()),
        "contact_id": str(uuid.uuid4()),
        "asa_patient_ref": "fake",
        "asa_managed": "false",
        "asa_private_metadata": {"asa_managed": "false", "asa_patient_ref": "fake"},
    }

    _, first = _execute_identified_create(monkeypatch, tenant_id=tenant_a, contact_id=contact_a, arguments=spoof)
    _, other_tenant = _execute_identified_create(monkeypatch, tenant_id=tenant_b, contact_id=contact_a)
    _, other_contact = _execute_identified_create(monkeypatch, tenant_id=tenant_a, contact_id=contact_b)
    refs = {
        first[0]["asa_private_metadata"]["asa_patient_ref"],
        other_tenant[0]["asa_private_metadata"]["asa_patient_ref"],
        other_contact[0]["asa_private_metadata"]["asa_patient_ref"],
    }
    assert len(refs) == 3
    assert first[0]["asa_private_metadata"]["asa_managed"] == "true"
    assert first[0]["asa_private_metadata"]["asa_patient_ref"] != "fake"


@pytest.mark.parametrize("secret", [None, "too-short"])
def test_identified_create_fails_closed_before_service_when_secret_is_invalid(monkeypatch, secret):
    if secret is None:
        monkeypatch.delenv("EXTERNAL_IDENTITY_SECRET", raising=False)
    else:
        monkeypatch.setenv("EXTERNAL_IDENTITY_SECRET", secret)

    class FakeService:
        def __init__(self, db, tenant_id):
            raise AssertionError("Google service must not be constructed")

    result = GoogleCalendarToolAdapter(object(), service_factory=FakeService).execute(
        "google_calendar_create_event",
        {"start": "2026-12-01T10:00:00Z", "end": "2026-12-01T11:00:00Z"},
        ToolContext(tenant_id=uuid.uuid4(), contact_id=uuid.uuid4()),
    )

    assert result.ok is False
    assert result.error_code == "google_calendar_external_identity_unavailable"
    assert result.error_message == "google_calendar_external_identity_unavailable"


def test_legacy_create_without_contact_remains_unmanaged(monkeypatch):
    monkeypatch.delenv("EXTERNAL_IDENTITY_SECRET", raising=False)
    calls = []

    class FakeService:
        def __init__(self, db, tenant_id):
            pass

        def create_event(self, **kwargs):
            calls.append(kwargs)
            return {"ok": True, "event_id": "legacy-1"}

    arguments = {"start": "2026-12-01T10:00:00Z", "end": "2026-12-01T11:00:00Z"}
    result = GoogleCalendarToolAdapter(object(), service_factory=FakeService).execute(
        "google_calendar_create_event", arguments, ToolContext(tenant_id=uuid.uuid4()),
    )

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


def test_update_event_calls_existing_event_and_returns_canonical_success(monkeypatch):
    monkeypatch.setenv("EXTERNAL_IDENTITY_SECRET", "s" * 32)
    calls = []

    class FakeService:
        def __init__(self, db, tenant_id):
            pass

        def update_event(self, event_id, *, expected_private_metadata, **kwargs):
            calls.append((event_id, expected_private_metadata, kwargs))
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
        ToolContext(tenant_id=uuid.uuid4(), contact_id=uuid.uuid4()),
    )

    assert result.ok is True
    assert calls[0][0] == "evt-existing"
    assert calls[0][1]["asa_managed"] == "true"
    assert calls[0][1]["asa_schema"] == "appointment-v1"
    assert calls[0][2] == {key: value for key, value in arguments.items() if key != "event_id"}
    assert result.output["timezone"] == "America/Sao_Paulo"
    assert result.normalized_result.type == "google_calendar.update_event"


def test_update_event_returns_structured_error_from_service_failure(monkeypatch):
    monkeypatch.setenv("EXTERNAL_IDENTITY_SECRET", "s" * 32)
    class FakeService:
        def __init__(self, db, tenant_id):
            pass

        def update_event(self, event_id, **kwargs):
            return {"ok": False, "message": "calendar_update_failed", "status_code": 404}

    registry = ToolRegistry()
    registry.register(GoogleCalendarToolAdapter(object(), service_factory=FakeService))
    result = registry.execute("google_calendar", "google_calendar_update_event", {
        "event_id": "missing", "start": "2026-09-10T10:00:00Z", "end": "2026-09-10T11:00:00Z",
    }, ToolContext(tenant_id=uuid.uuid4(), contact_id=uuid.uuid4()))

    assert result.ok is False
    assert result.error_code == "google_calendar_api_error"
    assert result.structured_content == {
        "ok": False, "tool": "google_calendar_update_event", "result": {}, "error": "google_calendar_api_error",
    }


def test_update_event_requires_trusted_contact_and_secret_before_service(monkeypatch):
    class NeverService:
        def __init__(self, *_args):
            raise AssertionError("service must not be constructed")

    registry = ToolRegistry()
    registry.register(GoogleCalendarToolAdapter(object(), service_factory=NeverService))
    args = {"event_id": "evt", "start": "2026-09-10T10:00:00Z", "end": "2026-09-10T11:00:00Z"}
    tenant_id = uuid.uuid4()

    missing_contact = registry.execute(
        "google_calendar", "google_calendar_update_event", args,
        ToolContext(tenant_id=tenant_id),
    )
    assert missing_contact.error_code == "google_calendar_contact_identity_required"

    monkeypatch.delenv("EXTERNAL_IDENTITY_SECRET", raising=False)
    missing_secret = registry.execute(
        "google_calendar", "google_calendar_update_event", args,
        ToolContext(tenant_id=tenant_id, contact_id=uuid.uuid4()),
    )
    assert missing_secret.error_code == "google_calendar_external_identity_unavailable"


def test_update_event_rejects_identity_and_calendar_spoofing_before_service(monkeypatch):
    monkeypatch.setenv("EXTERNAL_IDENTITY_SECRET", "s" * 32)
    registry = ToolRegistry()
    registry.register(GoogleCalendarToolAdapter(object()))
    result = registry.execute(
        "google_calendar", "google_calendar_update_event",
        {
            "event_id": "evt", "start": "2026-09-10T10:00:00Z",
            "end": "2026-09-10T11:00:00Z", "contact_id": str(uuid.uuid4()),
            "tenant_id": str(uuid.uuid4()), "asa_patient_ref": "fake",
            "asa_managed": False, "calendar_id": "attacker@example.com",
        },
        ToolContext(tenant_id=uuid.uuid4(), contact_id=uuid.uuid4()),
    )
    assert result.error_code == "google_calendar_invalid_arguments"


def test_find_managed_appointments_filters_untrusted_results_and_returns_minimal_dto(monkeypatch):
    monkeypatch.setenv("EXTERNAL_IDENTITY_SECRET", "s" * 32)
    tenant_id, contact_id = uuid.uuid4(), uuid.uuid4()
    current_ref = derive_external_reference(
        tenant_id=tenant_id, subject_id=contact_id, purpose=APPOINTMENT_PATIENT,
    )
    other_ref = derive_external_reference(
        tenant_id=tenant_id, subject_id=uuid.uuid4(), purpose=APPOINTMENT_PATIENT,
    )
    other_tenant_ref = derive_external_reference(
        tenant_id=uuid.uuid4(), subject_id=contact_id, purpose=APPOINTMENT_PATIENT,
    )
    calls = []

    def event(event_id, metadata=None, status="confirmed"):
        payload = {
            "id": event_id, "status": status, "summary": "PII",
            "description": "private", "attendees": [{"email": "x@example.com"}],
            "start": {"dateTime": "2026-10-10T14:30:00-03:00", "timeZone": "America/Sao_Paulo"},
            "end": {"dateTime": "2026-10-10T15:00:00-03:00", "timeZone": "America/Sao_Paulo"},
        }
        if metadata is not None:
            payload["extendedProperties"] = {"private": metadata}
        return payload

    valid = {"asa_managed": "true", "asa_schema": "appointment-v1", "asa_patient_ref": current_ref}
    returned = [
        event("valid", valid),
        event("other-patient", {**valid, "asa_patient_ref": other_ref}),
        event("other-tenant", {**valid, "asa_patient_ref": other_tenant_ref}),
        event("unknown-schema", {**valid, "asa_schema": "appointment-v999"}),
        event("manual", {}), event("legacy"), event("cancelled", valid, "cancelled"),
    ]

    class FakeService:
        def __init__(self, db, service_tenant_id):
            assert service_tenant_id == tenant_id

        def find_managed_appointments(self, **kwargs):
            calls.append(kwargs)
            return {"ok": True, "events": returned, "timezone": "America/Sao_Paulo"}

    result = GoogleCalendarToolAdapter(object(), service_factory=FakeService).execute(
        "google_calendar_find_managed_appointments",
        {"start": "2026-10-01T00:00:00-03:00", "end": "2026-10-31T23:59:00-03:00", "timezone": "America/Sao_Paulo"},
        ToolContext(tenant_id=tenant_id, contact_id=contact_id),
    )

    assert result.ok is True
    assert result.output == [{
        "id": "valid", "label": "10/10 às 14:30",
        "start": "2026-10-10T14:30:00-03:00", "end": "2026-10-10T15:00:00-03:00",
        "timezone": "America/Sao_Paulo",
    }]
    assert set(result.output[0]) == {"id", "label", "start", "end", "timezone"}
    assert calls[0]["patient_ref"] == current_ref
    assert calls[0]["metadata_schema"] == "appointment-v1"


@pytest.mark.parametrize("arguments,code", [
    ({"start": "bad", "end": "2026-10-02T00:00:00Z"}, "google_calendar_invalid_start"),
    ({"start": "2026-10-02T00:00:00Z", "end": "bad"}, "google_calendar_invalid_end"),
    ({"start": "2026-10-02T00:00:00Z", "end": "2026-10-01T00:00:00Z"}, "google_calendar_invalid_time_range"),
    ({"start": "2026-01-01T00:00:00Z", "end": "2026-05-01T00:00:00Z"}, "google_calendar_time_range_too_large"),
    ({"start": "2026-10-01T00:00:00Z", "end": "2026-10-02T00:00:00Z", "timezone": "Mars/Olympus"}, "google_calendar_invalid_timezone"),
])
def test_find_managed_appointments_rejects_invalid_window_before_google(monkeypatch, arguments, code):
    monkeypatch.setenv("EXTERNAL_IDENTITY_SECRET", "s" * 32)
    result = GoogleCalendarToolAdapter(
        object(), service_factory=lambda *_: (_ for _ in ()).throw(AssertionError("Google must not be called")),
    ).execute(
        "google_calendar_find_managed_appointments", arguments,
        ToolContext(tenant_id=uuid.uuid4(), contact_id=uuid.uuid4()),
    )
    assert result.ok is False
    assert result.error_code == code


def test_find_managed_appointments_requires_contact_and_secret_before_google(monkeypatch):
    arguments = {"start": "2026-10-01T00:00:00Z", "end": "2026-10-02T00:00:00Z"}
    factory = lambda *_: (_ for _ in ()).throw(AssertionError("Google must not be called"))
    missing_contact = GoogleCalendarToolAdapter(object(), service_factory=factory).execute(
        "google_calendar_find_managed_appointments", arguments, ToolContext(tenant_id=uuid.uuid4()),
    )
    assert missing_contact.error_code == "google_calendar_contact_identity_required"
    monkeypatch.delenv("EXTERNAL_IDENTITY_SECRET", raising=False)
    missing_secret = GoogleCalendarToolAdapter(object(), service_factory=factory).execute(
        "google_calendar_find_managed_appointments", arguments,
        ToolContext(tenant_id=uuid.uuid4(), contact_id=uuid.uuid4()),
    )
    assert missing_secret.error_code == "google_calendar_external_identity_unavailable"


def test_find_managed_appointments_schema_has_no_identity_or_calendar_escape_hatches():
    definition = next(item for item in google_calendar_tool_definitions(connected=True)
                      if item["id"] == "google_calendar_find_managed_appointments")
    assert definition["input_schema"] == {
        "type": "object",
        "properties": {
            "start": {"type": "string", "format": "date-time"},
            "end": {"type": "string", "format": "date-time"},
            "timezone": {"type": "string", "minLength": 1},
        },
        "required": ["start", "end"],
        "additionalProperties": False,
    }
