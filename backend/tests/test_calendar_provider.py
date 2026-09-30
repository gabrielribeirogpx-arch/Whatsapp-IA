from __future__ import annotations

import uuid

import pytest

from app.models.integration_connection import IntegrationConnection
from app.services.calendar_provider import CalendarProvider
from app.services.calendar_provider_resolver import (
    CalendarProviderResolutionError,
    CalendarProviderResolver,
)
from app.services.google_calendar_provider import GoogleCalendarProvider
from app.tools.context import ToolContext


class _Scalars:
    def __init__(self, row):
        self._row = row

    def first(self):
        return self._row


class _Result:
    def __init__(self, row):
        self._row = row

    def scalars(self):
        return _Scalars(self._row)


class _Db:
    def __init__(self, row=None):
        self.row = row

    def execute(self, _statement):
        return _Result(self.row)


class _RecordingService:
    calls = []

    def __init__(self, db, tenant_id, connection_id):
        self.calls.append(("init", db, tenant_id, connection_id))

    def __getattr__(self, operation):
        def call(*args, **kwargs):
            self.calls.append((operation, args, kwargs))
            return {"ok": True, "operation": operation, "args": args, "kwargs": kwargs}

        return call


def _connection(tenant_id, **overrides):
    values = {
        "id": uuid.uuid4(),
        "tenant_id": tenant_id,
        "provider": "google_calendar",
        "auth_type": "oauth2",
        "status": "active",
    }
    values.update(overrides)
    return IntegrationConnection(**values)


def test_resolver_returns_calendar_provider_bound_to_exact_context_connection():
    tenant_id = uuid.uuid4()
    connection = _connection(tenant_id)
    db = _Db(connection)
    _RecordingService.calls = []

    provider = CalendarProviderResolver(db, service_factory=_RecordingService).resolve(
        ToolContext(tenant_id=tenant_id, integration_connection_id=connection.id)
    )

    assert isinstance(provider, GoogleCalendarProvider)
    assert isinstance(provider, CalendarProvider)
    assert _RecordingService.calls == [("init", db, tenant_id, connection.id)]


@pytest.mark.parametrize(
    ("connection_changes", "context_tenant"),
    [
        ({"tenant_id": uuid.uuid4()}, None),
        ({"status": "revoked"}, None),
        ({"provider": "google_drive"}, None),
        ({"auth_type": "api_key"}, None),
    ],
)
def test_resolver_fails_closed_for_invalid_connection_binding(connection_changes, context_tenant):
    tenant_id = context_tenant or uuid.uuid4()
    connection_tenant = connection_changes.pop("tenant_id", tenant_id)
    connection = _connection(connection_tenant, **connection_changes)

    with pytest.raises(CalendarProviderResolutionError) as error:
        CalendarProviderResolver(_Db(connection), service_factory=_RecordingService).resolve(
            ToolContext(tenant_id=tenant_id, integration_connection_id=connection.id)
        )

    assert error.value.code == "google_calendar_connection_required"


def test_resolver_rejects_unsupported_provider():
    with pytest.raises(CalendarProviderResolutionError) as error:
        CalendarProviderResolver(_Db()).resolve(
            ToolContext(tenant_id=uuid.uuid4()), provider="model_selected"
        )

    assert error.value.code == "calendar_provider_unsupported"


def test_native_provider_requires_complete_server_binding():
    with pytest.raises(CalendarProviderResolutionError) as error:
        CalendarProviderResolver(_Db()).resolve(
            ToolContext(tenant_id=uuid.uuid4(), contact_id=uuid.uuid4()), provider="wazza_native"
        )
    assert error.value.code == "wazza_native_binding_required"


def test_google_provider_is_a_transparent_delegate_for_every_real_operation():
    _RecordingService.calls = []
    provider = GoogleCalendarProvider(
        object(), uuid.uuid4(), uuid.uuid4(), service_factory=_RecordingService
    )

    assert provider.check_availability(start="a", end="b")["operation"] == "check_availability"
    assert provider.create_event(start="a", end="b")["operation"] == "create_event"
    assert provider.find_managed_appointments(
        start="a", end="b", timezone="UTC", patient_ref="patient", metadata_schema="v1"
    )["operation"] == "find_managed_appointments"
    assert provider.update_event("event", start="a")["operation"] == "update_event"
    assert provider.delete_event("event")["operation"] == "delete_event"
    assert provider.list_events(max_results=1)["operation"] == "list_events"
