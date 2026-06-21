from __future__ import annotations

import uuid
from datetime import datetime, timedelta

import pytest

from app.models.integration_connection import IntegrationConnection
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
    def __init__(self, status_code=200, data=None, text=None):
        self.status_code = status_code
        self._data = data or {}
        self.text = text if text is not None else str(self._data)
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
    assert result["message"] == "google_calendar_refresh_invalid_grant"
    assert result["user_message"] == "A autorização do Google Calendar expirou ou foi revogada. Reconecte o Google Calendar."


def test_invalid_grant_refresh_logs_diagnostics_without_tokens(monkeypatch, caplog):
    tenant_id = uuid.uuid4(); db = FakeDb(); _connect(db, tenant_id, expires_at=datetime.utcnow() - timedelta(minutes=1))
    caplog.set_level("INFO")
    body = {"error": "invalid_grant", "error_description": "Bad Request"}

    monkeypatch.setattr("app.services.google_calendar_service.requests.post", lambda *a, **k: Resp(400, body, text='{"error":"invalid_grant","error_description":"Bad Request"}'))

    result = GoogleCalendarService(db, tenant_id).list_events()

    assert result["ok"] is False
    assert result["message"] == "google_calendar_refresh_invalid_grant"
    assert "GOOGLE_CALENDAR_TOKEN_REFRESH_REQUEST" in caplog.text
    assert "GOOGLE_CALENDAR_TOKEN_REFRESH_FAILED" in caplog.text
    assert "invalid_grant" in caplog.text
    assert "Bad Request" in caplog.text
    assert "client_id_present" in caplog.text
    assert "client_secret_present" in caplog.text
    assert "refresh_token_present" in caplog.text
    assert "refresh-token" not in caplog.text
    assert "client-secret" not in caplog.text


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


def test_refresh_token_encrypted_attempts_decrypt_before_missing(monkeypatch):
    tenant_id = uuid.uuid4(); db = FakeDb(); conn = _connect(db, tenant_id, expires_at=datetime.utcnow() - timedelta(minutes=1))
    calls = []
    def fake_decrypt(value):
        calls.append(value)
        if value == conn.refresh_token_encrypted:
            return None
        return IntegrationConnectionService.decrypt_credential(value)
    monkeypatch.setattr("app.services.google_calendar_service.IntegrationConnectionService.decrypt_credential_strict", fake_decrypt)
    result = GoogleCalendarService(db, tenant_id).list_events()
    assert conn.refresh_token_encrypted in calls
    assert result == {"ok": False, "message": "google_calendar_refresh_token_empty_after_decrypt"}


def test_refresh_token_decrypt_error_returns_clear_code(monkeypatch):
    tenant_id = uuid.uuid4(); db = FakeDb(); conn = _connect(db, tenant_id, expires_at=datetime.utcnow() - timedelta(minutes=1))
    calls = []
    def fake_decrypt(value):
        calls.append(value)
        if value == conn.refresh_token_encrypted:
            raise ValueError("bad token")
        return IntegrationConnectionService.decrypt_credential(value)
    monkeypatch.setattr("app.services.google_calendar_service.IntegrationConnectionService.decrypt_credential_strict", fake_decrypt)
    result = GoogleCalendarService(db, tenant_id).list_events()
    assert conn.refresh_token_encrypted in calls
    assert result == {"ok": False, "message": "google_calendar_token_decrypt_failed"}


def test_multiple_connections_uses_latest_active_same_tenant(monkeypatch):
    tenant_id = uuid.uuid4(); other_tenant = uuid.uuid4(); db = FakeDb()
    old = IntegrationConnection(tenant_id=tenant_id, provider="google_calendar", auth_type="oauth2", status="active", access_token_encrypted=IntegrationConnectionService.encrypt_credential("old"), refresh_token_encrypted=IntegrationConnectionService.encrypt_credential("old-refresh"), updated_at=datetime.utcnow() - timedelta(days=2))
    disconnected = IntegrationConnection(tenant_id=tenant_id, provider="google_calendar", auth_type="oauth2", status="disconnected", access_token_encrypted=IntegrationConnectionService.encrypt_credential("disconnected"), refresh_token_encrypted=IntegrationConnectionService.encrypt_credential("disconnected-refresh"), updated_at=datetime.utcnow())
    latest = IntegrationConnection(tenant_id=tenant_id, provider="google_calendar", auth_type="oauth2", status="active", access_token_encrypted=IntegrationConnectionService.encrypt_credential("latest"), refresh_token_encrypted=IntegrationConnectionService.encrypt_credential("latest-refresh"), updated_at=datetime.utcnow() - timedelta(hours=1))
    other = IntegrationConnection(tenant_id=other_tenant, provider="google_calendar", auth_type="oauth2", status="active", access_token_encrypted=IntegrationConnectionService.encrypt_credential("other"), refresh_token_encrypted=IntegrationConnectionService.encrypt_credential("other-refresh"), updated_at=datetime.utcnow() + timedelta(days=1))
    db.connections = [old, disconnected, latest, other]
    auths = []
    monkeypatch.setattr("app.services.google_calendar_service.requests.request", lambda *a, **k: auths.append(k["headers"]["Authorization"]) or Resp(200, {"items": []}))
    result = GoogleCalendarService(db, tenant_id).list_events()
    assert result["ok"] is True
    assert auths == ["Bearer latest"]


def test_check_availability_uses_same_request_auth_path_as_list_events(monkeypatch):
    tenant_id = uuid.uuid4(); db = FakeDb(); _connect(db, tenant_id)
    calls = []

    def fake_request(self, method, path, *, params=None, json_body=None, retry=True, auth_trace=None):
        calls.append({"method": method, "path": path, "params": params, "json_body": json_body, "retry": retry, "has_auth_trace": auth_trace is not None})
        if auth_trace is not None:
            auth_trace.update(access_token_present=True, refresh_token_present=True, refresh_attempted=False, refresh_success=False, refresh_failed_reason=None)
        if method == "GET":
            return True, {"items": []}, 200
        return True, {"calendars": {"primary": {"busy": []}}}, 200

    monkeypatch.setattr(GoogleCalendarService, "_request", fake_request)

    service = GoogleCalendarService(db, tenant_id)
    assert service.list_events()["ok"] is True
    assert service.check_availability(start="2026-06-20T10:00:00", end="2026-06-20T11:00:00")["ok"] is True

    assert calls[0]["method"] == "GET"
    assert calls[0]["path"] == "/calendars/primary/events"
    assert calls[0]["has_auth_trace"] is False
    assert calls[1]["method"] == "POST"
    assert calls[1]["path"] == "/freeBusy"
    assert calls[1]["has_auth_trace"] is True


def test_check_availability_logs_auth_diagnostics(monkeypatch, caplog):
    tenant_id = uuid.uuid4(); db = FakeDb(); _connect(db, tenant_id)
    caplog.set_level("INFO")

    def fake_request(method, url, **kwargs):
        return Resp(200, {"calendars": {"primary": {"busy": []}}})

    monkeypatch.setattr("app.services.google_calendar_service.requests.request", fake_request)

    result = GoogleCalendarService(db, tenant_id).check_availability(start="2026-06-20T10:00:00", end="2026-06-20T11:00:00")

    assert result["ok"] is True
    for event in [
        "GOOGLE_CALENDAR_CHECK_AVAILABILITY_START",
        "GOOGLE_CALENDAR_CHECK_AVAILABILITY_AUTH_READY",
        "GOOGLE_CALENDAR_CHECK_AVAILABILITY_REQUEST",
        "GOOGLE_CALENDAR_CHECK_AVAILABILITY_RESULT",
    ]:
        assert event in caplog.text
    assert "access_token_present" in caplog.text
    assert "refresh_token_present" in caplog.text
    assert "refresh_attempted" in caplog.text
    assert "refresh_success" in caplog.text
    assert "refresh_failed_reason" in caplog.text
