from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
import traceback
import uuid
from collections.abc import Mapping
from pathlib import Path
from urllib.parse import urlparse

import requests

from fastapi import APIRouter, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/flow-media", tags=["flow-media"])
media_router = APIRouter(prefix="/api/media", tags=["media"])
public_router = APIRouter(tags=["flow-media-public"])


def _default_upload_root() -> Path:
    configured = os.getenv("FLOW_MEDIA_UPLOAD_DIR")
    if configured:
        return Path(configured)
    upload_root = os.getenv("UPLOAD_ROOT")
    if upload_root:
        return Path(upload_root) / "flow-media"
    return Path("/data/uploads/flow-media")


UPLOAD_ROOT = _default_upload_root()
UPLOAD_STORAGE_RAILWAY_DETAIL = (
    "Storage persistente de mídia não configurado. Configure um Railway Volume em /data "
    "ou defina FLOW_MEDIA_UPLOAD_DIR/UPLOAD_ROOT para um caminho persistente compartilhado pela API e worker."
)
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
VIDEO_META_MAX_BYTES = int(os.getenv("FLOW_MEDIA_VIDEO_META_MAX_BYTES", str(16 * 1024 * 1024)))
VIDEO_INCOMPATIBLE_DETAIL = "Este vídeo não é compatível com WhatsApp. Use MP4 H.264 com áudio AAC."
VIDEO_PREFLIGHT_RETRY_SECONDS = float(os.getenv("FLOW_MEDIA_VIDEO_PREFLIGHT_RETRY_SECONDS", "5"))
VIDEO_PREFLIGHT_RETRY_INTERVAL_SECONDS = float(os.getenv("FLOW_MEDIA_VIDEO_PREFLIGHT_RETRY_INTERVAL_SECONDS", "0.5"))
VIDEO_PREFLIGHT_TIMEOUT_SECONDS = float(os.getenv("FLOW_MEDIA_VIDEO_PREFLIGHT_TIMEOUT_SECONDS", "8"))


def _is_railway_environment() -> bool:
    return bool(os.getenv("RAILWAY_ENVIRONMENT") or os.getenv("RAILWAY_PUBLIC_DOMAIN") or os.getenv("RAILWAY_PROJECT_ID"))


def _upload_storage_status() -> dict[str, object]:
    root = UPLOAD_ROOT
    exists = root.exists()
    writable = False
    data_mount_persistent = os.path.ismount("/data")
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".write-test"
        probe.write_text("ok")
        probe.unlink(missing_ok=True)
        exists = root.exists()
        writable = True
    except OSError:
        exists = root.exists()
        writable = False
    return {"root": str(root), "exists": exists, "writable": writable, "data_mount_persistent": data_mount_persistent}


def log_upload_storage_status() -> dict[str, object]:
    status = _upload_storage_status()
    logger.info("[UPLOAD STORAGE] root=%s exists=%s writable=%s", status["root"], status["exists"], status["writable"])
    print(f'[UPLOAD STORAGE] root={status["root"]} exists={status["exists"]} writable={status["writable"]}', flush=True)
    return status


def _ensure_upload_storage_ready() -> None:
    status = _upload_storage_status()
    logger.info("[UPLOAD STORAGE] root=%s exists=%s writable=%s", status["root"], status["exists"], status["writable"])
    root = Path(str(status["root"]))
    if not status["writable"]:
        raise HTTPException(status_code=503, detail=UPLOAD_STORAGE_RAILWAY_DETAIL)
    if _is_railway_environment() and not root.is_absolute():
        raise HTTPException(status_code=503, detail=UPLOAD_STORAGE_RAILWAY_DETAIL)
    if _is_railway_environment() and str(root).startswith("/data/") and not status.get("data_mount_persistent"):
        raise HTTPException(status_code=503, detail=UPLOAD_STORAGE_RAILWAY_DETAIL)


def _max_upload_bytes() -> int:
    raw_value = os.getenv("MEDIA_UPLOAD_MAX_BYTES") or os.getenv("FLOW_MEDIA_MAX_UPLOAD_BYTES")
    if not raw_value:
        return DEFAULT_MAX_UPLOAD_BYTES
    try:
        return max(1, int(raw_value))
    except ValueError:
        return DEFAULT_MAX_UPLOAD_BYTES



def _header_int(headers: Mapping[str, str], name: str) -> int:
    try:
        return int(str(headers.get(name) or "0").split(";", 1)[0].strip())
    except (TypeError, ValueError):
        return 0


def _video_preflight_exception_text(exc: BaseException | None) -> str:
    if exc is None:
        return ""
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip().replace("\n", " | ")


def _log_video_preflight(
    *,
    public_url: str,
    head_status: int | None,
    get_status: int | None,
    content_type: str,
    content_length: int,
    exception: BaseException | None,
) -> None:
    exception_text = _video_preflight_exception_text(exception)
    logger.info(
        "[VIDEO PREFLIGHT]\npublic_url=%s\nhead_status=%s\nget_status=%s\ncontent_type=%s\ncontent_length=%s\nexception=%s",
        public_url,
        head_status if head_status is not None else "",
        get_status if get_status is not None else "",
        content_type,
        content_length if content_length > 0 else "",
        exception_text,
    )
    if exception is not None:
        logger.warning(
            "[VIDEO PREFLIGHT EXCEPTION] public_url=%s",
            public_url,
            exc_info=(type(exception), exception, exception.__traceback__),
        )


def _successful_video_preflight_status(status_code: int | None) -> bool:
    return status_code in {200, 206}


def _validate_video_headers_once(
    *, public_url: str, local_size: int
) -> tuple[bool, str, int, int | None, int | None, BaseException | None]:
    head_status: int | None = None
    get_status: int | None = None
    content_type = ""
    content_length = 0
    exception: BaseException | None = None
    usable_response: requests.Response | None = None

    try:
        head_response = requests.head(public_url, allow_redirects=True, timeout=VIDEO_PREFLIGHT_TIMEOUT_SECONDS)
        head_status = head_response.status_code
        if _successful_video_preflight_status(head_status):
            usable_response = head_response
    except requests.RequestException as exc:
        exception = exc

    try:
        get_response = requests.get(
            public_url,
            headers={"Range": "bytes=0-0"},
            stream=True,
            allow_redirects=True,
            timeout=VIDEO_PREFLIGHT_TIMEOUT_SECONDS,
        )
        get_status = get_response.status_code
        if _successful_video_preflight_status(get_status):
            usable_response = get_response
    except requests.RequestException as exc:
        exception = exc

    if usable_response is not None:
        content_type = str(usable_response.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        content_length = _header_int(usable_response.headers, "content-length") or local_size

    _log_video_preflight(
        public_url=public_url,
        head_status=head_status,
        get_status=get_status,
        content_type=content_type,
        content_length=content_length,
        exception=exception,
    )
    return usable_response is not None, content_type, content_length, head_status, get_status, exception


def _validate_internal_video_file(*, suffix: str, content_type: str, local_size: int) -> None:
    if suffix not in {".mp4", ".3gp"}:
        raise HTTPException(status_code=400, detail=VIDEO_INCOMPATIBLE_DETAIL)
    if content_type not in {"video/mp4", "video/3gpp"}:
        raise HTTPException(status_code=415, detail=VIDEO_INCOMPATIBLE_DETAIL)
    expected_type = "video/mp4" if suffix == ".mp4" else "video/3gpp"
    if content_type != expected_type:
        raise HTTPException(status_code=400, detail=VIDEO_INCOMPATIBLE_DETAIL)
    if local_size <= 0:
        raise HTTPException(status_code=400, detail="Arquivo de vídeo vazio.")
    if local_size > VIDEO_META_MAX_BYTES:
        raise HTTPException(status_code=413, detail=f"Vídeo excede o limite de {VIDEO_META_MAX_BYTES} bytes.")


def _validate_video_headers(*, public_url: str, suffix: str, local_size: int) -> tuple[str, int]:
    deadline = time.monotonic() + max(0, VIDEO_PREFLIGHT_RETRY_SECONDS)
    last_result: tuple[bool, str, int, int | None, int | None, BaseException | None] | None = None
    while True:
        last_result = _validate_video_headers_once(public_url=public_url, local_size=local_size)
        is_reachable, content_type, content_length, _head_status, _get_status, _exception = last_result
        if is_reachable:
            expected_type = "video/mp4" if suffix == ".mp4" else "video/3gpp"
            if content_type != expected_type or content_length <= 0 or content_length > VIDEO_META_MAX_BYTES:
                logger.warning(
                    "[VIDEO PREFLIGHT] public URL preflight returned unexpected headers, upload accepted because local file validation passed public_url=%s content_type=%s content_length=%s expected_type=%s",
                    public_url,
                    content_type,
                    content_length,
                    expected_type,
                )
            return content_type or expected_type, content_length or local_size
        if time.monotonic() >= deadline:
            logger.warning(
                "[VIDEO PREFLIGHT] public URL preflight failed, upload accepted because local file validation passed public_url=%s",
                public_url,
            )
            return ("video/mp4" if suffix == ".mp4" else "video/3gpp"), local_size
        time.sleep(max(0.1, VIDEO_PREFLIGHT_RETRY_INTERVAL_SECONDS))


def _validate_video_with_ffprobe(path: Path) -> None:
    ffprobe_bin = os.getenv("FFPROBE_BIN", "ffprobe")
    try:
        result = subprocess.run(
            [
                ffprobe_bin,
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except FileNotFoundError:
        logger.info("[MEDIA VIDEO FFPROBE SKIPPED] reason=ffprobe_not_found path=%s", path)
        return
    except subprocess.SubprocessError as exc:
        logger.warning("[MEDIA VIDEO FFPROBE FAILED] path=%s error=%s", path, exc)
        raise HTTPException(status_code=400, detail=VIDEO_INCOMPATIBLE_DETAIL) from exc

    if result.returncode != 0:
        logger.warning("[MEDIA VIDEO FFPROBE INVALID] path=%s stderr=%s", path, result.stderr)
        raise HTTPException(status_code=400, detail=VIDEO_INCOMPATIBLE_DETAIL)
    try:
        metadata = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as exc:
        logger.warning("[MEDIA VIDEO FFPROBE JSON ERROR] path=%s error=%s", path, exc)
        raise HTTPException(status_code=400, detail=VIDEO_INCOMPATIBLE_DETAIL) from exc

    streams = metadata.get("streams") or []
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    video_codec = str((video_streams[0] or {}).get("codec_name") or "").lower() if video_streams else ""
    audio_codec = str((audio_streams[0] or {}).get("codec_name") or "").lower() if audio_streams else ""
    format_name = str((metadata.get("format") or {}).get("format_name") or "").lower()
    logger.info("[MEDIA VIDEO FFPROBE] path=%s format=%s video_codec=%s audio_codec=%s", path, format_name, video_codec, audio_codec or "none")
    if "mp4" not in format_name and path.suffix.lower() == ".mp4":
        raise HTTPException(status_code=400, detail=VIDEO_INCOMPATIBLE_DETAIL)
    if video_codec != "h264" or (audio_streams and audio_codec != "aac"):
        raise HTTPException(status_code=400, detail=VIDEO_INCOMPATIBLE_DETAIL)

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
    if content_type == "video/3gpp":
        compatible_suffixes.add(".3gp")
    if suffix and suffix not in compatible_suffixes:
        raise HTTPException(status_code=400, detail="Extensão não corresponde ao tipo do arquivo.")
    return suffix or expected


def _safe_original_stem(filename: str) -> str:
    stem = Path(filename or "").stem
    safe_stem = re.sub(r"[^A-Za-z0-9._-]+", "-", stem).strip(".-_")
    return safe_stem[:80] or "media"


def _configured_public_base_url() -> str | None:
    for env_name in ("PUBLIC_API_BASE_URL", "PUBLIC_BACKEND_URL", "API_PUBLIC_URL", "BACKEND_PUBLIC_URL"):
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
    return f"{scheme}://{host}".rstrip("/")


def _public_url(request: Request, filename: str) -> str:
    public_base = _configured_public_base_url() or _request_public_base_url(request)
    parsed = urlparse(public_base)
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
    _ensure_upload_storage_ready()
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
    if media_family == "video":
        try:
            _validate_internal_video_file(suffix=suffix, content_type=content_type, local_size=len(data))
            _validate_video_with_ffprobe(path)
            preflight_content_type, preflight_content_length = _validate_video_headers(public_url=public_url, suffix=suffix, local_size=len(data))
        except HTTPException:
            logger.warning("[MEDIA UPLOAD CLEANUP] reason=video_validation_failed local_path=%s public_url=%s", path, public_url)
            path.unlink(missing_ok=True)
            raise
    else:
        preflight_content_type, preflight_content_length = content_type, len(data)
    logger.info("[MEDIA UPLOAD] media_type=%s public_url=%s content_type=%s content_length=%s", media_family, public_url, preflight_content_type, preflight_content_length)
    logger.info(
        "[MEDIA UPLOAD DIAGNOSTIC] tenant_id=%s original_filename=%s stored_filename=%s media_type=%s public_url=%s local_path=%s exists=%s size=%s note=%s",
        request.state.tenant_id,
        file.filename,
        stored_filename,
        media_family,
        public_url,
        path,
        os.path.exists(path),
        os.path.getsize(path) if os.path.exists(path) else None,
        "new upload generates a uuid-prefixed URL; compare this public_url with published snapshot media_url",
    )
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
