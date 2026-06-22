from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.database import get_db
from app.routers import webhook


class _NoTenantDb:
    def execute(self, *_args, **_kwargs):
        return self

    def scalars(self):
        return self

    def first(self):
        return None


def _client(monkeypatch, verify_token: str = "TOKEN") -> TestClient:
    monkeypatch.setenv("VERIFY_TOKEN", verify_token)
    monkeypatch.delenv("WHATSAPP_VERIFY_TOKEN", raising=False)
    app = FastAPI()
    app.include_router(webhook.router)
    app.dependency_overrides[get_db] = lambda: _NoTenantDb()
    return TestClient(app)


def test_webhook_get_accepts_official_meta_query_params(monkeypatch):
    client = _client(monkeypatch)

    response = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "TOKEN",
            "hub.challenge": "123456",
        },
    )

    assert response.status_code == 200
    assert response.text == "123456"
    assert response.headers["content-type"].startswith("text/plain")


def test_webhook_get_rejects_invalid_token(monkeypatch):
    client = _client(monkeypatch)

    response = client.get(
        "/webhook",
        params={
            "hub.mode": "subscribe",
            "hub.verify_token": "WRONG",
            "hub.challenge": "123456",
        },
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "verify_token inválido"}


def test_webhook_get_rejects_missing_official_params(monkeypatch):
    client = _client(monkeypatch)

    response = client.get("/webhook", params={"hub.mode": "subscribe", "hub.verify_token": "TOKEN"})

    assert response.status_code == 400
    assert response.json() == {"detail": "hub.challenge ausente"}


def test_webhook_get_keeps_legacy_query_param_compatibility(monkeypatch):
    client = _client(monkeypatch)

    response = client.get(
        "/webhook",
        params={"mode": "subscribe", "verify_token": "TOKEN", "challenge": "123456"},
    )

    assert response.status_code == 200
    assert response.text == "123456"
