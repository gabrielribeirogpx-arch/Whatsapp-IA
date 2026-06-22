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


def test_media_upload_uses_public_api_base_url(tmp_path, monkeypatch):
    monkeypatch.setenv("PUBLIC_API_BASE_URL", "https://api.wazzaapi.com.br")
    monkeypatch.delenv("PUBLIC_BACKEND_URL", raising=False)
    monkeypatch.delenv("API_PUBLIC_URL", raising=False)
    monkeypatch.delenv("BACKEND_PUBLIC_URL", raising=False)
    client = _client(tmp_path, monkeypatch)

    response = client.post(
        "/api/media/upload",
        headers={**_headers(), "host": "api.wazzaapi.com.br", "x-forwarded-proto": "http"},
        files={"file": ("contrato.pdf", b"%PDF-1.4", "application/pdf")},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["url"].startswith("https://api.wazzaapi.com.br/uploads/flow-media/")
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
    monkeypatch.setattr(flow_media, "_validate_video_headers", lambda **kwargs: ("video/mp4", kwargs["local_size"]))
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


def test_video_preflight_accepts_get_when_head_fails(monkeypatch):
    class Response:
        def __init__(self, status_code, headers):
            self.status_code = status_code
            self.headers = headers

    monkeypatch.setattr(flow_media.requests, "head", lambda *args, **kwargs: Response(404, {}))
    monkeypatch.setattr(
        flow_media.requests,
        "get",
        lambda *args, **kwargs: Response(206, {"content-type": "video/mp4", "content-length": "12"}),
    )

    content_type, content_length = flow_media._validate_video_headers(
        public_url="https://api.example.com/uploads/flow-media/tenant/video.mp4",
        suffix=".mp4",
        local_size=12,
    )

    assert content_type == "video/mp4"
    assert content_length == 12


def test_video_preflight_retries_until_public_url_is_available(monkeypatch):
    class Response:
        def __init__(self, status_code, headers=None):
            self.status_code = status_code
            self.headers = headers or {}

    attempts = {"count": 0}

    def fake_head(*args, **kwargs):
        attempts["count"] += 1
        if attempts["count"] < 2:
            return Response(404)
        return Response(200, {"content-type": "video/mp4", "content-length": "12"})

    monkeypatch.setattr(flow_media, "VIDEO_PREFLIGHT_RETRY_SECONDS", 1)
    monkeypatch.setattr(flow_media, "VIDEO_PREFLIGHT_RETRY_INTERVAL_SECONDS", 0.1)
    monkeypatch.setattr(flow_media.requests, "head", fake_head)
    monkeypatch.setattr(flow_media.requests, "get", lambda *args, **kwargs: Response(404))

    content_type, content_length = flow_media._validate_video_headers(
        public_url="https://api.example.com/uploads/flow-media/tenant/video.mp4",
        suffix=".mp4",
        local_size=12,
    )

    assert attempts["count"] == 2
    assert content_type == "video/mp4"
    assert content_length == 12


def test_upload_storage_status_logs_root_exists_and_writable(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(flow_media, "UPLOAD_ROOT", tmp_path / "flow-media")

    status = flow_media.log_upload_storage_status()

    captured = capsys.readouterr()
    assert "[UPLOAD STORAGE]" in captured.out
    assert status["root"] == str(tmp_path / "flow-media")
    assert status["exists"] is True
    assert status["writable"] is True


def test_media_upload_fails_clearly_when_railway_storage_is_not_persistent(monkeypatch):
    monkeypatch.setattr(flow_media, "UPLOAD_ROOT", flow_media.Path("uploads/flow-media"))
    monkeypatch.setattr(flow_media, "_is_railway_environment", lambda: True)
    app = FastAPI()
    app.add_middleware(TenantContextMiddleware)
    app.include_router(flow_media.media_router)
    client = TestClient(app)

    response = client.post(
        "/api/media/upload",
        headers=_headers(),
        files={"file": ("foto.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )

    assert response.status_code == 503
    assert "Storage persistente" in response.json()["detail"]


def test_media_upload_fails_clearly_when_railway_data_volume_is_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(flow_media, "UPLOAD_ROOT", flow_media.Path("/data/uploads/flow-media"))
    monkeypatch.setattr(flow_media, "_is_railway_environment", lambda: True)
    monkeypatch.setattr(flow_media.os.path, "ismount", lambda path: False)
    app = FastAPI()
    app.add_middleware(TenantContextMiddleware)
    app.include_router(flow_media.media_router)
    client = TestClient(app)

    response = client.post(
        "/api/media/upload",
        headers=_headers(),
        files={"file": ("foto.png", b"\x89PNG\r\n\x1a\n", "image/png")},
    )

    assert response.status_code == 503
    assert "Storage persistente" in response.json()["detail"]
