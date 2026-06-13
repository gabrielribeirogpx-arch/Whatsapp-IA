from __future__ import annotations

import logging
import os
import re
import uuid
from pathlib import Path
from urllib.parse import urlparse

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/flow-media", tags=["flow-media"])
media_router = APIRouter(prefix="/api/media", tags=["media"])
public_router = APIRouter(tags=["flow-media-public"])

UPLOAD_ROOT = Path(os.getenv("FLOW_MEDIA_UPLOAD_DIR", "uploads/flow-media"))
ALLOWED_CONTENT_TYPES = {
    "image/jpeg", "image/png", "image/webp", "application/pdf",
    "audio/mpeg", "audio/mp3", "audio/ogg", "audio/webm", "audio/wav", "audio/aac", "audio/mp4",
    "video/mp4", "video/3gpp", "video/quicktime",
}
SAFE_SUFFIX_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/ogg": ".ogg",
    "audio/webm": ".webm",
    "audio/wav": ".wav",
    "audio/aac": ".aac",
    "audio/mp4": ".m4a",
    "video/mp4": ".mp4",
    "video/3gpp": ".3gp",
    "video/quicktime": ".mov",
}
ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".pdf", ".mp3", ".ogg", ".opus", ".wav", ".aac", ".m4a", ".mp4", ".3gp", ".mov", ".webm"}
CONTENT_TYPE_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
    ".pdf": "application/pdf",
    ".mp3": "audio/mpeg",
    ".ogg": "audio/ogg",
    ".opus": "audio/ogg",
    ".wav": "audio/wav",
    ".aac": "audio/aac",
    ".m4a": "audio/mp4",
    ".mp4": "video/mp4",
    ".3gp": "video/3gpp",
    ".mov": "video/quicktime",
    ".webm": "audio/webm",
}
DANGEROUS_SUFFIXES = {
    ".ade", ".adp", ".apk", ".app", ".appx", ".bat", ".cmd", ".com", ".cpl",
    ".dll", ".dmg", ".exe", ".gadget", ".hta", ".ins", ".iso", ".jar", ".js",
    ".jse", ".lib", ".lnk", ".mde", ".msc", ".msi", ".msp", ".mst", ".ps1",
    ".scr", ".sh", ".sys", ".vb", ".vbe", ".vbs", ".vxd", ".ws", ".wsc",
    ".wsf", ".wsh",
}
DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MEDIA_MAX_UPLOAD_BYTES = {"audio": 16 * 1024 * 1024, "video": 16 * 1024 * 1024}


def _max_upload_bytes() -> int:
    raw_value = os.getenv("MEDIA_UPLOAD_MAX_BYTES") or os.getenv("FLOW_MEDIA_MAX_UPLOAD_BYTES")
    if not raw_value:
        return DEFAULT_MAX_UPLOAD_BYTES
    try:
        return max(1, int(raw_value))
    except ValueError:
        return DEFAULT_MAX_UPLOAD_BYTES


def _original_suffixes(filename: str) -> list[str]:
    return [suffix.lower() for suffix in Path(filename or "").suffixes]


def _safe_suffix(filename: str, content_type: str) -> str:
    suffixes = _original_suffixes(filename)
    if any(suffix in DANGEROUS_SUFFIXES for suffix in suffixes):
        raise HTTPException(status_code=400, detail="Extensão de arquivo não permitida.")
    suffix = suffixes[-1] if suffixes else ""
    if suffix and suffix not in ALLOWED_SUFFIXES:
        raise HTTPException(status_code=400, detail="Extensão de arquivo não permitida para este tipo de mídia.")
    if suffix == ".jpeg" and content_type == "image/jpeg":
        return suffix
    expected = SAFE_SUFFIX_BY_CONTENT_TYPE[content_type]
    compatible_suffixes = {expected}
    if content_type == "image/jpeg":
        compatible_suffixes.add(".jpeg")
    if content_type == "audio/mpeg":
        compatible_suffixes.add(".mp3")
    if content_type == "audio/mp3":
        compatible_suffixes.add(".mp3")
    if content_type == "audio/ogg":
        compatible_suffixes.update({".ogg", ".opus"})
    if content_type == "audio/mp4":
        compatible_suffixes.update({".m4a", ".mp4"})
    if content_type == "video/mp4":
        compatible_suffixes.add(".mp4")
    if suffix and suffix not in compatible_suffixes:
        raise HTTPException(status_code=400, detail="Extensão não corresponde ao tipo do arquivo.")
    return suffix or expected


def _safe_original_stem(filename: str) -> str:
    stem = Path(filename or "").stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-_")
    return safe_stem[:80] or "media"


def _configured_public_base_url() -> str | None:
    for env_name in ("PUBLIC_BACKEND_URL", "API_PUBLIC_URL", "BACKEND_PUBLIC_URL"):
        value = str(os.getenv(env_name) or "").strip().rstrip("/")
        if value:
            return value
    return None


def _request_public_base_url(request: Request) -> str:
    base_url = str(request.base_url).rstrip("/")
    parsed = urlparse(base_url)
    forwarded_proto = str(request.headers.get("x-forwarded-proto") or "").split(",")[0].strip().lower()
    host = str(request.headers.get("x-forwarded-host") or request.headers.get("host") or parsed.netloc).split(",")[0].strip()
    scheme = forwarded_proto or parsed.scheme or "https"
    if host.endswith(".up.railway.app") or os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PUBLIC_DOMAIN"):
        scheme = "https"
    return f"{scheme}://{host}".rstrip("/")


def _public_url(request: Request, filename: str) -> str:
    public_base = _configured_public_base_url() or _request_public_base_url(request)
    parsed = urlparse(public_base)
    if parsed.netloc.endswith(".up.railway.app") and parsed.scheme != "https":
        public_base = f"https://{parsed.netloc}{parsed.path}".rstrip("/")
    return f"{public_base}/uploads/flow-media/{filename}"


@public_router.api_route("/uploads/flow-media/{tenant_id}/{filename:path}", methods=["GET", "HEAD"], include_in_schema=False)
async def get_public_flow_media(tenant_id: str, filename: str):
    safe_filename = Path(filename).name
    if not safe_filename or safe_filename != filename:
        raise HTTPException(status_code=404, detail="Media not found")

    media_path = (UPLOAD_ROOT / tenant_id / safe_filename).resolve()
    upload_root = UPLOAD_ROOT.resolve()
    if upload_root not in media_path.parents or not media_path.is_file():
        raise HTTPException(status_code=404, detail="Media not found")

    return FileResponse(
        media_path,
        media_type=CONTENT_TYPE_BY_SUFFIX.get(media_path.suffix.lower()),
        filename=safe_filename,
        content_disposition_type="inline",
    )


async def _upload_media(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    if not getattr(request.state, "tenant_id", None):
        raise HTTPException(status_code=400, detail="X-Tenant-ID é obrigatório")

    content_type = str(file.content_type or "").lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Tipo de arquivo não suportado. Use JPEG, PNG, WebP, PDF, áudio ou vídeo compatível.")

    suffix = _safe_suffix(file.filename or "", content_type)
    media_family = content_type.split("/", 1)[0]
    max_upload_bytes = MEDIA_MAX_UPLOAD_BYTES.get(media_family, _max_upload_bytes())
    data = await file.read(max_upload_bytes + 1)
    if len(data) > max_upload_bytes:
        raise HTTPException(status_code=413, detail=f"Arquivo maior que {max_upload_bytes} bytes.")

    tenant_dir = UPLOAD_ROOT / str(request.state.tenant_id)
    tenant_dir.mkdir(parents=True, exist_ok=True)
    stored_filename = f"{uuid.uuid4()}-{_safe_original_stem(file.filename or '')}{suffix}"
    path = tenant_dir / stored_filename
    path.write_bytes(data)

    public_filename = f"{request.state.tenant_id}/{stored_filename}"
    public_url = _public_url(request, public_filename)
    logger.info("[MEDIA UPLOAD] public_url=%s", public_url)
    return JSONResponse({
        "url": public_url,
        "filename": file.filename or stored_filename,
        "mime_type": content_type,
        "size": len(data),
    })


@router.post("/upload")
async def upload_flow_media(request: Request, file: UploadFile = File(...)):
    return await _upload_media(request, file)


@media_router.post("/upload")
async def upload_media(request: Request, file: UploadFile = File(...)):
    return await _upload_media(request, file)
