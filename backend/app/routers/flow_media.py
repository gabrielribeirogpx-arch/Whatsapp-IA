from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/flow-media", tags=["flow-media"])
media_router = APIRouter(prefix="/api/media", tags=["media"])

UPLOAD_ROOT = Path(os.getenv("FLOW_MEDIA_UPLOAD_DIR", "uploads/flow-media"))
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
SAFE_SUFFIX_BY_CONTENT_TYPE = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "application/pdf": ".pdf",
}
ALLOWED_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".pdf"}
DANGEROUS_SUFFIXES = {
    ".ade", ".adp", ".apk", ".app", ".appx", ".bat", ".cmd", ".com", ".cpl",
    ".dll", ".dmg", ".exe", ".gadget", ".hta", ".ins", ".iso", ".jar", ".js",
    ".jse", ".lib", ".lnk", ".mde", ".msc", ".msi", ".msp", ".mst", ".ps1",
    ".scr", ".sh", ".sys", ".vb", ".vbe", ".vbs", ".vxd", ".ws", ".wsc",
    ".wsf", ".wsh",
}
DEFAULT_MAX_UPLOAD_BYTES = 10 * 1024 * 1024


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
    if suffix and suffix != expected:
        raise HTTPException(status_code=400, detail="Extensão não corresponde ao tipo do arquivo.")
    return suffix or expected


def _public_url(request: Request, filename: str) -> str:
    public_base = os.getenv("PUBLIC_BACKEND_URL", str(request.base_url).rstrip("/"))
    return f"{public_base}/uploads/flow-media/{filename}"


async def _upload_media(request: Request, file: UploadFile = File(...)) -> JSONResponse:
    if not getattr(request.state, "tenant_id", None):
        raise HTTPException(status_code=400, detail="X-Tenant-ID é obrigatório")

    content_type = str(file.content_type or "").lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Tipo de arquivo não suportado. Use JPEG, PNG, WebP ou PDF.")

    suffix = _safe_suffix(file.filename or "", content_type)
    max_upload_bytes = _max_upload_bytes()
    data = await file.read(max_upload_bytes + 1)
    if len(data) > max_upload_bytes:
        raise HTTPException(status_code=413, detail=f"Arquivo maior que {max_upload_bytes} bytes.")

    tenant_dir = UPLOAD_ROOT / str(request.state.tenant_id)
    tenant_dir.mkdir(parents=True, exist_ok=True)
    stored_filename = f"{uuid.uuid4()}{suffix}"
    path = tenant_dir / stored_filename
    path.write_bytes(data)

    public_filename = f"{request.state.tenant_id}/{stored_filename}"
    return JSONResponse({
        "url": _public_url(request, public_filename),
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
