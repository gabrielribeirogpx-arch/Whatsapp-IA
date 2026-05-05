from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable

from app.core.redis_client import get_redis_client

logger = logging.getLogger(__name__)

TTL_TENANT_SECONDS = 300
TTL_FLOW_SECONDS = 300
TTL_BOT_CONFIG_SECONDS = 300
TTL_CONVERSATION_STATE_SECONDS = 900


def _get_json(key: str) -> dict[str, Any] | None:
    raw = get_redis_client().get(key)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("event=cache_decode_error key=%s", key)
        return None


def _set_json(key: str, value: dict[str, Any], ttl_seconds: int) -> None:
    get_redis_client().setex(key, ttl_seconds, json.dumps(value, default=str))


def cache_aside_json(key: str, ttl_seconds: int, loader: Callable[[], dict[str, Any] | None]) -> dict[str, Any] | None:
    cached = _get_json(key)
    if cached is not None:
        return cached
    loaded = loader()
    if loaded is not None:
        _set_json(key, loaded, ttl_seconds)
    return loaded


def get_conversation_state(tenant_id: str, conversation_id: str) -> dict[str, Any] | None:
    return _get_json(f"conversation_state:{tenant_id}:{conversation_id}")


def set_conversation_state(tenant_id: str, conversation_id: str, payload: dict[str, Any], ttl_seconds: int = TTL_CONVERSATION_STATE_SECONDS) -> None:
    _set_json(f"conversation_state:{tenant_id}:{conversation_id}", payload, ttl_seconds)


def invalidate_tenant_and_flow_cache(tenant_id: str) -> None:
    redis = get_redis_client()
    redis.delete(f"tenant:{tenant_id}")
    redis.delete(f"flow:{tenant_id}")
    redis.delete(f"bot_config:{tenant_id}")


def check_rate_limit(tenant_id: str, max_per_minute: int = 120) -> bool:
    redis = get_redis_client()
    key = f"rate:{tenant_id}:{int(time.time() // 60)}"
    current = redis.incr(key)
    if current == 1:
        redis.expire(key, 120)
    return int(current) <= int(max_per_minute)
