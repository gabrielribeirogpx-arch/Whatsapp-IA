from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.services.google_calendar_service import GoogleCalendarService, NOT_CONNECTED_MESSAGE
from app.services.integration_connection_service import IntegrationConnectionService
from tests.test_integration_connection_service import FakeDb


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("OAUTH_TOKEN_ENCRYPTION_KEY", "integration-test-secret")
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_CALENDAR_CLIENT_SECRET", "client-secret")


def _connect(db, tenant_id, access="access-token", refresh="refresh-token", expires_at=None):
    return IntegrationConnectionService(db).upsert_connection(
        tenant_id=tenant_id,
        provider="google_calendar",
        auth_type="oauth2",
        access_token=access,
        refresh_token=refresh,
        expires_at=expires_at or datetime.utcnow() + timedelta(hours=1),
    )


class Resp:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {}
        self.content = b"" if status_code == 204 else b"{}"
    def json(self):
        return self._data


def test_tenant_without_connection_returns_ok_false():
    result = GoogleCalendarService(FakeDb(), uuid.uuid4()).create_event(title="Reunião")
    assert result == {"ok": False, "message": NOT_CONNECTED_MESSAGE}


def test_tenant_with_connection_creates_event(monkeypatch, caplog):
    tenant_id = uuid.uuid4(); db = FakeDb(); _connect(db, tenant_id)
    seen = {}
    def fake_request(method, url, **kwargs):
        seen.update(method=method, url=url, headers=kwargs["headers"], json=kwargs["json"])
        return Resp(200, {"id": "evt1", "htmlLink": "https://calendar/evt1", "summary": "Reunião", "start": {"dateTime": "2026-06-20T10:00:00-03:00"}, "end": {"dateTime": "2026-06-20T11:00:00-03:00"}})
    monkeypatch.setattr("app.services.google_calendar_service.requests.request", fake_request)
    result = GoogleCalendarService(db, tenant_id).create_event(title="Reunião", start="2026-06-20T10:00:00", end="2026-06-20T11:00:00")
    assert result["ok"] is True and result["event_id"] == "evt1"
    assert seen["method"] == "POST" and seen["url"].endswith("/calendars/primary/events")
    assert seen["headers"]["Authorization"] == "Bearer access-token"
    assert "access-token" not in str(result) and "refresh-token" not in str(result)
    assert "access-token" not in caplog.text and "refresh-token" not in caplog.text


def test_list_events_isolates_tenant(monkeypatch):
    tenant_a = uuid.uuid4(); tenant_b = uuid.uuid4(); db = FakeDb(); _connect(db, tenant_a, access="a"); _connect(db, tenant_b, access="b")
    auths = []
    monkeypatch.setattr("app.services.google_calendar_service.requests.request", lambda *a, **k: auths.append(k["headers"]["Authorization"]) or Resp(200, {"items": []}))
    assert GoogleCalendarService(db, tenant_b).list_events()["ok"] is True
    assert auths == ["Bearer b"]


def test_401_refreshes_and_retries_once(monkeypatch):
    tenant_id = uuid.uuid4(); db = FakeDb(); conn = _connect(db, tenant_id, access="old", refresh="refresh")
    calls = []
    def fake_request(method, url, **kwargs):
        calls.append(kwargs["headers"]["Authorization"])
        return Resp(401 if len(calls) == 1 else 200, {"items": []})
    def fake_post(url, data, **kwargs):
        assert data["refresh_token"] == "refresh"
        return Resp(200, {"access_token": "new", "expires_in": 3600})
    monkeypatch.setattr("app.services.google_calendar_service.requests.request", fake_request)
    monkeypatch.setattr("app.services.google_calendar_service.requests.post", fake_post)
    result = GoogleCalendarService(db, tenant_id).list_events()
    assert result["ok"] is True
    assert calls == ["Bearer old", "Bearer new"]
    assert IntegrationConnectionService.decrypt_credential(conn.access_token_encrypted) == "new"


def test_invalid_refresh_token_returns_clear_error(monkeypatch):
    tenant_id = uuid.uuid4(); db = FakeDb(); _connect(db, tenant_id, expires_at=datetime.utcnow() - timedelta(minutes=1))
    monkeypatch.setattr("app.services.google_calendar_service.requests.post", lambda *a, **k: Resp(400, {"error": "invalid_grant"}))
    result = GoogleCalendarService(db, tenant_id).list_events()
    assert result["ok"] is False
    assert result["message"] == "Não foi possível renovar o acesso ao Google Calendar."


def test_delete_event_calls_correct_calendar(monkeypatch):
    tenant_id = uuid.uuid4(); db = FakeDb(); _connect(db, tenant_id)
    seen = {}
    monkeypatch.setattr("app.services.google_calendar_service.requests.request", lambda method, url, **kwargs: seen.update(method=method, url=url) or Resp(204, {}))
    assert GoogleCalendarService(db, tenant_id).delete_event("evt-delete") == {"ok": True, "deleted": True, "event_id": "evt-delete"}
    assert seen == {"method": "DELETE", "url": "https://www.googleapis.com/calendar/v3/calendars/primary/events/evt-delete"}


def test_check_availability_calls_freebusy(monkeypatch):
    tenant_id = uuid.uuid4(); db = FakeDb(); _connect(db, tenant_id)
    seen = {}
    def fake_request(method, url, **kwargs):
        seen.update(method=method, url=url, json=kwargs["json"])
        return Resp(200, {"calendars": {"primary": {"busy": [{"start": "s", "end": "e"}]}}})
    monkeypatch.setattr("app.services.google_calendar_service.requests.request", fake_request)
    result = GoogleCalendarService(db, tenant_id).check_availability(start="2026-06-20T10:00:00", end="2026-06-20T11:00:00")
    assert result["ok"] is True and result["busy"] == [{"start": "s", "end": "e"}]
    assert seen["method"] == "POST" and seen["url"].endswith("/freeBusy")
    assert seen["json"]["items"] == [{"id": "primary"}]
