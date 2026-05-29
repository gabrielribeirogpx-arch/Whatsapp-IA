from __future__ import annotations

import os
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any

import requests
from fastapi import HTTPException, Request

TURNSTILE_VERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"
DEV_TOKENS = {"dev-turnstile-token", "dev-bypass-turnstile"}


@dataclass
class _Bucket:
    count: int
    reset_at: float


_RATE_LIMITS: dict[str, _Bucket] = {}
_RATE_LIMIT_LOCK = Lock()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def turnstile_is_required() -> bool:
    if _env_bool("TURNSTILE_DISABLED", False):
        return False
    return _env_bool("TURNSTILE_ENABLED", True)


def get_client_ip(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",", 1)[0].strip() or "unknown"
    real_ip = request.headers.get("x-real-ip", "").strip()
    if real_ip:
        return real_ip
    return request.client.host if request.client else "unknown"


def _clean_rate_limits(now: float) -> None:
    expired = [key for key, bucket in _RATE_LIMITS.items() if bucket.reset_at <= now]
    for key in expired:
        _RATE_LIMITS.pop(key, None)


def enforce_rate_limit(*, key: str, limit: int, window_seconds: int, detail: str = "Muitas tentativas. Aguarde alguns minutos e tente novamente.") -> None:
    now = time.time()
    with _RATE_LIMIT_LOCK:
        _clean_rate_limits(now)
        bucket = _RATE_LIMITS.get(key)
        if bucket is None:
            _RATE_LIMITS[key] = _Bucket(count=1, reset_at=now + window_seconds)
            return
        if bucket.count >= limit:
            retry_after = max(1, int(bucket.reset_at - now))
            raise HTTPException(status_code=429, detail=detail, headers={"Retry-After": str(retry_after)})
        bucket.count += 1


def validate_turnstile_or_raise(*, token: str | None, request: Request, action: str) -> None:
    if not turnstile_is_required():
        print("[TURNSTILE VALIDATION SUCCESS]", f"action={action} mode=disabled")
        return

    secret_key = os.getenv("TURNSTILE_SECRET_KEY", "").strip()
    env = os.getenv("ENV", os.getenv("APP_ENV", os.getenv("NODE_ENV", "production"))).strip().lower()
    host = request.headers.get("host", "").split(":", 1)[0].lower()
    dev_bypass_allowed = _env_bool("TURNSTILE_DEV_BYPASS", False) or env in {"development", "dev", "local", "test"} or host in {"localhost", "127.0.0.1"}
    token = (token or "").strip()

    if not secret_key:
        if dev_bypass_allowed and token in DEV_TOKENS:
            print("[TURNSTILE VALIDATION SUCCESS]", f"action={action} mode=dev-bypass")
            return
        print("[TURNSTILE VALIDATION FAILED]", f"action={action} reason=missing-secret")
        raise HTTPException(status_code=503, detail="Proteção anti-bot indisponível. Tente novamente em instantes.")

    if not token:
        print("[TURNSTILE VALIDATION FAILED]", f"action={action} reason=missing-token")
        raise HTTPException(status_code=403, detail="Validação anti-bot obrigatória.")

    try:
        response = requests.post(
            TURNSTILE_VERIFY_URL,
            data={
                "secret": secret_key,
                "response": token,
                "remoteip": get_client_ip(request),
            },
            timeout=5,
        )
        response.raise_for_status()
        result: dict[str, Any] = response.json()
    except requests.RequestException as exc:
        print("[TURNSTILE VALIDATION FAILED]", f"action={action} reason=network error={type(exc).__name__}")
        raise HTTPException(status_code=503, detail="Não foi possível validar a proteção anti-bot. Tente novamente.") from exc
    except ValueError as exc:
        print("[TURNSTILE VALIDATION FAILED]", f"action={action} reason=invalid-response")
        raise HTTPException(status_code=503, detail="Resposta anti-bot inválida. Tente novamente.") from exc

    if result.get("success") is True:
        hostname = result.get("hostname", "unknown")
        print("[TURNSTILE VALIDATION SUCCESS]", f"action={action} hostname={hostname}")
        return

    codes = ",".join(str(code) for code in result.get("error-codes", [])) or "unknown"
    print("[TURNSTILE VALIDATION FAILED]", f"action={action} reason=siteverify-failed codes={codes}")
    raise HTTPException(status_code=403, detail="Validação anti-bot inválida ou expirada.")
