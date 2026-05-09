from __future__ import annotations

import json
import logging
import time
import uuid

from app.core.redis_client import get_redis_client

DELAY_ZSET_KEY = "flow_delays"

logger = logging.getLogger(__name__)


def enqueue_delay(
    tenant_id: uuid.UUID,
    phone: str,
    next_node_id: uuid.UUID,
    seconds: int,
    *,
    flow_id: uuid.UUID | None = None,
    flow_session_id: uuid.UUID | None = None,
    flow_version_id: uuid.UUID | None = None,
    delay_node_id: uuid.UUID | None = None,
    expected_current_node_id: uuid.UUID | None = None,
) -> None:
    execute_at = int(time.time()) + max(0, int(seconds))
    payload = {
        "tenant_id": str(tenant_id),
        "phone": phone,
        "user_identifier": phone,
        "flow_id": str(flow_id) if flow_id else None,
        "flow_session_id": str(flow_session_id) if flow_session_id else None,
        "flow_version_id": str(flow_version_id) if flow_version_id else None,
        "delay_node_id": str(delay_node_id) if delay_node_id else None,
        "expected_current_node_id": str(expected_current_node_id) if expected_current_node_id else None,
        "next_node_id": str(next_node_id),
        "scheduled_at": int(time.time()),
    }
    serialized_payload = json.dumps(payload, sort_keys=True)

    redis_client = get_redis_client()
    redis_client.zadd(DELAY_ZSET_KEY, {serialized_payload: execute_at})

    logger.info(
        "Delay enfileirado tenant_id=%s phone=%s next_node_id=%s execute_at=%s seconds=%s",
        tenant_id,
        phone,
        next_node_id,
        execute_at,
        seconds,
    )


def clear_delays_for_runtime_reset(
    *,
    tenant_id: uuid.UUID,
    user_identifier: str,
    flow_id: uuid.UUID,
    flow_session_ids: list[uuid.UUID],
) -> int:
    redis_client = get_redis_client()
    removed = 0
    flow_session_id_set = {str(item) for item in flow_session_ids}
    for raw_payload, _score in redis_client.zscan_iter(DELAY_ZSET_KEY):
        try:
            serialized_payload = raw_payload.decode("utf-8") if isinstance(raw_payload, bytes) else str(raw_payload)
            payload = json.loads(serialized_payload)
        except Exception:
            continue

        if str(payload.get("tenant_id") or "") != str(tenant_id):
            continue
        if str(payload.get("flow_id") or "") != str(flow_id):
            continue

        payload_phone = str(payload.get("phone") or payload.get("user_identifier") or "")
        payload_session_id = str(payload.get("flow_session_id") or "")
        if payload_phone != str(user_identifier) and payload_session_id not in flow_session_id_set:
            continue

        removed += int(redis_client.zrem(DELAY_ZSET_KEY, serialized_payload) or 0)
    return removed
