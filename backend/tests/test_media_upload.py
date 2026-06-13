from __future__ import annotations

import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.tenant_context import TenantContextMiddleware
from app.routers import flow_media


def _client(tmp_path, monkeypatch, max_bytes: int = 1024) -> TestClient:
    monkeypatch.setattr(flow_media, "UPLOAD_ROOT", tmp_path)
    monkeypatch.setenv("MEDIA_UPLOAD_MAX_BYTES", str(max_bytes))
    app = FastAPI()
    app.add_middleware(TenantContextMiddleware)
    app.include_router(flow_media.public_router)
    app.include_router(flow_media.media_router)
    return TestClient(app)


def _headers() -> dict[str, str]:
    return {"X-Tenant-ID": str(uuid.uuid4())}


def test_media_upload_accepts_valid_png(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/media/upload",
        headers=_headers(),
        files={"file": ("foto.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["url"].endswith(".png")
    assert body["filename"] == "foto.png"
    assert body["mime_type"] == "image/png"
    assert body["size"] == 8


def test_media_upload_rejects_invalid_mime_type(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/media/upload",
        headers=_headers(),
        files={"file": ("payload.txt", b"hello", "text/plain")},
    )

    assert response.status_code == 415


def test_media_upload_rejects_size_limit(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, max_bytes=4)

    response = client.post(
        "/api/media/upload",
        headers=_headers(),
        files={"file": ("foto.jpg", b"12345", "image/jpeg")},
    )

    assert response.status_code == 413


def test_media_upload_rejects_dangerous_extension(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/media/upload",
        headers=_headers(),
        files={"file": ("foto.jpg.exe", b"123", "image/jpeg")},
    )

    assert response.status_code == 400


def test_media_upload_returns_absolute_https_url_from_public_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_BACKEND_URL", "https://api.example.com/")
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/media/upload",
        headers=_headers(),
        files={"file": ("contrato.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["url"].startswith("https://api.example.com/uploads/flow-media/")
    assert not body["url"].startswith("/uploads/flow-media/")
    assert body["mime_type"] == "application/pdf"


def test_media_upload_fallback_forces_https_on_railway_host(tmp_path, monkeypatch):
    monkeypatch.delenv("PUBLIC_BACKEND_URL", raising=False)
    monkeypatch.delenv("API_PUBLIC_URL", raising=False)
    monkeypatch.delenv("BACKEND_PUBLIC_URL", raising=False)
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/media/upload",
        headers={**_headers(), "host": "whatsapp-ia-production-4699.up.railway.app", "x-forwarded-proto": "http"},
        files={"file": ("contrato.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["url"].startswith("https://whatsapp-ia-production-4699.up.railway.app/uploads/flow-media/")
    assert not body["url"].startswith("http://")


def test_media_upload_pdf_is_publicly_served_with_pdf_headers(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_BACKEND_URL", "https://api.example.com")
    client = _client(tmp_path, monkeypatch)
    tenant_id = str(uuid.uuid4())
    pdf_bytes = b"%PDF-1.4\n% test pdf bytes\n"

    upload_response = client.post(
        "/api/media/upload",
        headers={"X-Tenant-ID": tenant_id},
        files={"file": ("Edital.pdf", pdf_bytes, "application/pdf")},
    )

    assert upload_response.status_code == 200
    public_path = upload_response.json()["url"].removeprefix("https://api.example.com")

    head_response = client.head(public_path)
    assert head_response.status_code == 200
    assert head_response.headers["content-type"].startswith("application/pdf")
    assert int(head_response.headers["content-length"]) > 0
    assert 'filename="' in head_response.headers["content-disposition"]
    assert "Edital.pdf" in head_response.headers["content-disposition"]

    get_response = client.get(public_path)
    assert get_response.status_code == 200
    assert get_response.headers["content-type"].startswith("application/pdf")
    assert get_response.content == pdf_bytes
    assert get_response.content.startswith(b"%PDF")


def test_media_upload_accepts_valid_mp3(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/media/upload",
        headers=_headers(),
        files={"file": ("audio.mp3", b"ID3\x03\x00", "audio/mpeg")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["url"].endswith(".mp3")
    assert body["mime_type"] == "audio/mpeg"


def test_media_upload_accepts_valid_mp4(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/media/upload",
        headers=_headers(),
        files={"file": ("video.mp4", b"\x00\x00\x00\x18ftypmp42", "video/mp4")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["url"].endswith(".mp4")
    assert body["mime_type"] == "video/mp4"
