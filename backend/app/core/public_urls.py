from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

from fastapi import Request

logger = logging.getLogger(__name__)

DEFAULT_FRONTEND_URL = "https://app.wazzaapi.com.br"
DEFAULT_PUBLIC_API_BASE_URL = "https://api.wazzaapi.com.br"


def _absolute_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def frontend_url() -> str:
    configured = (os.getenv("FRONTEND_URL") or DEFAULT_FRONTEND_URL).strip().rstrip("/")
    if not _absolute_http_url(configured):
        logger.warning("INVALID_FRONTEND_URL value=%s fallback=%s", configured, DEFAULT_FRONTEND_URL)
        configured = DEFAULT_FRONTEND_URL
    logger.info("PUBLIC_URLS_RESOLVED frontend_url=%s public_api_base_url=%s", configured, public_api_base_url())
    return configured


def public_api_base_url(request: Request | None = None) -> str:
    configured = (
        os.getenv("PUBLIC_API_BASE_URL")
        or os.getenv("PUBLIC_BACKEND_URL")
        or os.getenv("API_PUBLIC_URL")
        or os.getenv("BACKEND_PUBLIC_URL")
        or ""
    ).strip().rstrip("/")
    if configured:
        if not _absolute_http_url(configured):
            logger.warning("INVALID_PUBLIC_API_BASE_URL value=%s fallback=%s", configured, DEFAULT_PUBLIC_API_BASE_URL)
            return DEFAULT_PUBLIC_API_BASE_URL
        return configured
    if request is not None:
        request_base = str(request.base_url).strip().rstrip("/")
        if _absolute_http_url(request_base):
            return request_base
    return DEFAULT_PUBLIC_API_BASE_URL


def oauth_callback_url(request: Request | None, path: str, legacy_env_name: str) -> str:
    configured = (os.getenv(legacy_env_name) or "").strip()
    source = legacy_env_name if configured else "PUBLIC_API_BASE_URL"
    callback_url = configured or f"{public_api_base_url(request)}{path}"
    if not _absolute_http_url(callback_url):
        raise ValueError(f"{legacy_env_name} inválida")
    logger.info("OAUTH_CALLBACK_RESOLVED provider_env=%s redirect_uri=%s source=%s", legacy_env_name, callback_url, source)
    return callback_url
