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
