from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

META_GRAPH_API_VERSION = os.getenv("META_GRAPH_API_VERSION", "v23.0").strip() or "v23.0"
META_GRAPH_BASE_URL = "https://graph.facebook.com"


class MetaApiError(RuntimeError):
    def __init__(self, message: str, status_code: int = 500, payload: dict[str, Any] | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.payload = payload or {}


class MetaCloudClient:
    def __init__(self, access_token: str, timeout_seconds: float = 15.0):
        self.access_token = (access_token or "").strip()
        self.base_url = f"{META_GRAPH_BASE_URL}/{META_GRAPH_API_VERSION}"
        self.timeout = httpx.Timeout(timeout_seconds)

    async def get(self, endpoint: str, *, params: dict[str, Any] | None = None, context: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("GET", endpoint, params=params, context=context)

    async def post(self, endpoint: str, *, payload: dict[str, Any], context: dict[str, Any] | None = None) -> dict[str, Any]:
        return await self._request("POST", endpoint, json=payload, context=context)

    async def _request(self, method: str, endpoint: str, **kwargs: Any) -> dict[str, Any]:
        context = kwargs.pop("context", {}) or {}
        endpoint_path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        url = f"{self.base_url}{endpoint_path}"
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        for attempt in range(1, 4):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.request(method, url, headers=headers, **kwargs)
                if response.status_code >= 400:
                    self._raise_api_error(response, endpoint_path, context)
                return response.json()
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                if attempt == 3:
                    logger.error("[META API ERROR] transport tenant_id=%s provider_id=%s template_id=%s graph_endpoint=%s status_code=%s detail=%s",
                                 context.get("tenant_id"), context.get("provider_id"), context.get("template_id"), endpoint_path, 0, str(exc))
                    raise MetaApiError("Falha de conexão com a Meta. Tente novamente.", status_code=503) from exc
                await asyncio.sleep(attempt * 0.4)

    def _raise_api_error(self, response: httpx.Response, endpoint: str, context: dict[str, Any]) -> None:
        payload = {}
        response_headers = {
            "x-fb-trace-id": response.headers.get("x-fb-trace-id"),
            "x-fb-request-id": response.headers.get("x-fb-request-id"),
            "x-business-use-case-usage": response.headers.get("x-business-use-case-usage"),
            "www-authenticate": response.headers.get("www-authenticate"),
        }
        try:
            payload = response.json()
        except Exception:
            payload = {"raw": response.text}
        if isinstance(payload, dict):
            payload.setdefault("raw", response.text)
            payload["headers"] = response_headers

        err = payload.get("error", {}) if isinstance(payload, dict) else {}
        message = err.get("message") or "Erro ao comunicar com Meta Graph API"
        friendly = _friendly_error(message, response.status_code)
        logger.error("[META API ERROR] tenant_id=%s provider_id=%s template_id=%s graph_endpoint=%s status_code=%s meta_message=%s",
                     context.get("tenant_id"), context.get("provider_id"), context.get("template_id"), endpoint, response.status_code, message)
        raise MetaApiError(friendly, status_code=response.status_code, payload=payload)


def _friendly_error(message: str, status_code: int) -> str:
    normalized = (message or "").lower()
    if "expired" in normalized or "session has expired" in normalized:
        return "Token da Meta expirado. Gere um novo token temporário."
    if "permission" in normalized or status_code == 403:
        return "Permissão negada pela Meta. Revise escopos do app e permissões."
    if "phone_number_id" in normalized:
        return "phone_number_id inválido na configuração."
    if "waba" in normalized:
        return "waba_id inválido na configuração."
    if status_code == 429:
        return "Limite de requisições da Meta atingido. Tente novamente em instantes."
    return "Falha na validação com a Meta Cloud API."
