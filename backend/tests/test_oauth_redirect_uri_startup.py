from __future__ import annotations

import pytest

from app.core.startup_checks import verify_oauth_redirect_uris


def test_startup_validates_google_redirect_uri(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.delenv("GOOGLE_REDIRECT_URI", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_ID", raising=False)
    monkeypatch.delenv("GMAIL_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("GMAIL_ENABLED", raising=False)
    monkeypatch.delenv("ENABLE_GMAIL", raising=False)

    with pytest.raises(RuntimeError, match="GOOGLE_REDIRECT_URI"):
        verify_oauth_redirect_uris()


def test_startup_validates_gmail_redirect_uri_when_gmail_enabled(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://app.example.com/api/integrations/google-calendar/callback")
    monkeypatch.setenv("GMAIL_CLIENT_ID", "gmail-client-id")
    monkeypatch.delenv("GMAIL_REDIRECT_URI", raising=False)

    with pytest.raises(RuntimeError, match="GMAIL_REDIRECT_URI"):
        verify_oauth_redirect_uris()


def test_startup_accepts_separate_calendar_and_gmail_redirect_uris(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("GOOGLE_REDIRECT_URI", "https://app.example.com/api/integrations/google-calendar/callback")
    monkeypatch.setenv("GMAIL_CLIENT_ID", "gmail-client-id")
    monkeypatch.setenv("GMAIL_REDIRECT_URI", "https://app.example.com/api/integrations/gmail/callback")

    verify_oauth_redirect_uris()
