from __future__ import annotations

import os
import uuid
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

router = APIRouter(prefix="/api/flow-media", tags=["flow-media"])

UPLOAD_ROOT = Path(os.getenv("FLOW_MEDIA_UPLOAD_DIR", "uploads/flow-media"))
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024


def _safe_suffix(filename: str, content_type: str) -> str:
    suffix = Path(filename or "").suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".pdf"}:
        return suffix
    return ".pdf" if content_type == "application/pdf" else ".bin"


@router.post("/upload")
async def upload_flow_media(request: Request, file: UploadFile = File(...)):
    content_type = str(file.content_type or "").lower()
    if content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(status_code=415, detail="Tipo de arquivo não suportado. Use imagem ou PDF.")

    data = await file.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Arquivo maior que 10MB.")

    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    filename = f"{uuid.uuid4()}{_safe_suffix(file.filename or '', content_type)}"
    path = UPLOAD_ROOT / filename
    path.write_bytes(data)

    public_base = os.getenv("PUBLIC_BACKEND_URL", str(request.base_url).rstrip("/"))
    public_url = f"{public_base}/uploads/flow-media/{filename}"
    return JSONResponse({"url": public_url, "filename": file.filename, "content_type": content_type, "size": len(data)})
