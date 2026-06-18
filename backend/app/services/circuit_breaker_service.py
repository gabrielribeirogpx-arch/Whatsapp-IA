from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from enum import StrEnum
from typing import Any, Callable, TypeVar

from app.core.redis_client import get_redis_client

logger = logging.getLogger(__name__)


class CircuitBreakerOpen(Exception):
    pass


class CircuitBreakerState(StrEnum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


F = TypeVar("F", bound=Callable[..., Any])
_LOCAL_STATE: dict[str, tuple[float, dict[str, Any]]] = {}
_REDIS_WARNING_DEADLINE = 0.0


def _env_bool(name: str, default: bool) -> bool:
    return str(os.getenv(name, str(default))).strip().lower() not in {"0", "false", "no", "off"}


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def _enabled() -> bool:
    return _env_bool("CIRCUIT_BREAKER_ENABLED", True)


def _defaults(failure_threshold: int | None, success_threshold: int | None, window_seconds: int | None, cooldown_seconds: int | None) -> tuple[int, int, int, int]:
    return (
        int(failure_threshold or _env_int("CIRCUIT_BREAKER_FAILURE_THRESHOLD", 5)),
        int(success_threshold or _env_int("CIRCUIT_BREAKER_SUCCESS_THRESHOLD", 2)),
        int(window_seconds or _env_int("CIRCUIT_BREAKER_WINDOW_SECONDS", 60)),
        int(cooldown_seconds or _env_int("CIRCUIT_BREAKER_COOLDOWN_SECONDS", 30)),
    )


def normalize_key(key: str) -> str:
    value = str(key or "global:unknown").strip().lower()
    value = re.sub(r"[^a-z0-9:_\-.]", "_", value)[:220]
    return value if value.startswith("cb:") else f"cb:{value}"


def key_hash(key: str) -> str:
    return hashlib.sha256(normalize_key(key).encode("utf-8")).hexdigest()[:16]


def sanitize_reason(reason: Any) -> str | None:
    if reason is None:
        return None
    text = str(reason).replace("\n", " ").replace("\r", " ").strip()
    text = re.sub(r"(?i)([?&](?:key|token|api_key|access_token)=)[^&\s]+", r"\1[REDACTED]", text)
    text = re.sub(r"(?i)((?:authorization|api[-_]?key|token|secret|password)\s*[:=]\s*)(bearer\s+)?\S+", r"\1[REDACTED]", text)
    return text[:200]


def _metadata(key: str, state: str, *, open_: bool, reason: str | None = None) -> dict[str, Any]:
    return {"circuit_breaker_checked": True, "circuit_breaker_key_hash": key_hash(key), "circuit_breaker_state": state, "circuit_breaker_open": open_, "circuit_breaker_reason": sanitize_reason(reason)}


def _redis() -> Any | None:
    global _REDIS_WARNING_DEADLINE
    try:
        client = get_redis_client()
        client.ping()
        return client
    except Exception as exc:
        now = time.monotonic()
        if now >= _REDIS_WARNING_DEADLINE:
            logger.warning("[CIRCUIT BREAKER] redis_unavailable fallback=local error=%s", type(exc).__name__)
            _REDIS_WARNING_DEADLINE = now + 60
        return None


def _load(storage_key: str) -> dict[str, Any]:
    now = time.time()
    redis = _redis()
    if redis is not None:
        raw = redis.get(storage_key)
        return json.loads(raw) if raw else {}
    expires, data = _LOCAL_STATE.get(storage_key, (0, {}))
    if expires and expires < now:
        _LOCAL_STATE.pop(storage_key, None)
        return {}
    return dict(data)


def _save(storage_key: str, data: dict[str, Any], ttl: int) -> None:
    redis = _redis()
    if redis is not None:
        redis.setex(storage_key, max(1, ttl), json.dumps(data, separators=(",", ":")))
    else:
        _LOCAL_STATE[storage_key] = (time.time() + max(1, ttl), dict(data))


def check_circuit(key: str, failure_threshold: int | None = None, success_threshold: int | None = None, window_seconds: int | None = None, cooldown_seconds: int | None = None) -> dict[str, Any]:
    if not _enabled():
        return _metadata(key, CircuitBreakerState.CLOSED, open_=False)
    failure_threshold, success_threshold, window_seconds, cooldown_seconds = _defaults(failure_threshold, success_threshold, window_seconds, cooldown_seconds)
    storage_key = normalize_key(key)
    now = time.time()
    data = _load(storage_key)
    state = data.get("state") or CircuitBreakerState.CLOSED
    opened_at = float(data.get("opened_at") or 0)
    if state == CircuitBreakerState.OPEN and now - opened_at >= cooldown_seconds:
        state = CircuitBreakerState.HALF_OPEN
        data.update({"state": state, "successes": 0, "half_open_calls": 0})
    if state == CircuitBreakerState.OPEN:
        meta = _metadata(key, state, open_=True, reason=data.get("reason") or "circuit_open")
        logger.warning("[CIRCUIT BREAKER OPEN] key_hash=%s state=%s", meta["circuit_breaker_key_hash"], state)
        raise CircuitBreakerOpen("Integração temporariamente indisponível.")
    if state == CircuitBreakerState.HALF_OPEN:
        calls = int(data.get("half_open_calls") or 0)
        if calls >= max(1, success_threshold):
            meta = _metadata(key, state, open_=True, reason="half_open_probe_limit")
            raise CircuitBreakerOpen("Integração temporariamente indisponível.")
        data["half_open_calls"] = calls + 1
    _save(storage_key, data or {"state": CircuitBreakerState.CLOSED, "failures": []}, window_seconds + cooldown_seconds + 30)
    return _metadata(key, str(state), open_=False)


def record_success(key: str) -> dict[str, Any]:
    if not _enabled():
        return _metadata(key, CircuitBreakerState.CLOSED, open_=False)
    _, success_threshold, window_seconds, cooldown_seconds = _defaults(None, None, None, None)
    storage_key = normalize_key(key)
    data = _load(storage_key)
    state = data.get("state") or CircuitBreakerState.CLOSED
    if state == CircuitBreakerState.HALF_OPEN:
        successes = int(data.get("successes") or 0) + 1
        if successes >= success_threshold:
            data = {"state": CircuitBreakerState.CLOSED, "failures": [], "successes": 0}
            state = CircuitBreakerState.CLOSED
        else:
            data["successes"] = successes
    else:
        data = {"state": CircuitBreakerState.CLOSED, "failures": [], "successes": 0}
        state = CircuitBreakerState.CLOSED
    _save(storage_key, data, window_seconds + cooldown_seconds + 30)
    return _metadata(key, str(state), open_=False)


def record_failure(key: str, reason: Any = None) -> dict[str, Any]:
    if not _enabled():
        return _metadata(key, CircuitBreakerState.CLOSED, open_=False, reason=reason)
    failure_threshold, _, window_seconds, cooldown_seconds = _defaults(None, None, None, None)
    storage_key = normalize_key(key)
    now = time.time()
    data = _load(storage_key)
    failures = [ts for ts in data.get("failures", []) if now - float(ts) <= window_seconds]
    failures.append(now)
    state = data.get("state") or CircuitBreakerState.CLOSED
    safe_reason = sanitize_reason(reason) or type(reason).__name__ if reason is not None else None
    if state == CircuitBreakerState.HALF_OPEN or len(failures) >= failure_threshold:
        state = CircuitBreakerState.OPEN
        data = {"state": state, "failures": failures, "opened_at": now, "reason": safe_reason}
    else:
        data = {"state": CircuitBreakerState.CLOSED, "failures": failures, "reason": safe_reason}
    _save(storage_key, data, window_seconds + cooldown_seconds + 30)
    return _metadata(key, str(state), open_=state == CircuitBreakerState.OPEN, reason=safe_reason)


def call_with_circuit(key: str, fn: F, *args: Any, **kwargs: Any) -> Any:
    check_circuit(key)
    try:
        result = fn(*args, **kwargs)
    except Exception as exc:
        record_failure(key, reason=type(exc).__name__)
        raise
    record_success(key)
    return result
