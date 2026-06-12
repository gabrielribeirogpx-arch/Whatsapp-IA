from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.core.redis_client import get_redis_client
from app.services.redis_realtime_service import redis_broker

PRESENCE_TTL_SECONDS = 45
TYPING_TTL_SECONDS = 5


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe(value: Any) -> str:
    return str(value).strip()


class PresenceService:
    """Redis-backed ephemeral presence and typing state scoped by tenant/conversation."""

    def __init__(self, redis_client: Any | None = None) -> None:
        self.redis = redis_client or get_redis_client()

    def presence_key(self, tenant_id: Any, conversation_id: Any, participant_id: Any) -> str:
        return f"presence:{_safe(tenant_id)}:{_safe(conversation_id)}:{_safe(participant_id)}"

    def last_seen_key(self, tenant_id: Any, conversation_id: Any, participant_id: Any) -> str:
        return f"presence:last_seen:{_safe(tenant_id)}:{_safe(conversation_id)}:{_safe(participant_id)}"

    def typing_key(self, tenant_id: Any, conversation_id: Any, participant_id: Any) -> str:
        return f"typing:{_safe(tenant_id)}:{_safe(conversation_id)}:{_safe(participant_id)}"

    def mark_online(
        self,
        *,
        tenant_id: Any,
        conversation_id: Any,
        participant_id: Any,
        participant_type: str = "agent",
        participant_name: str | None = None,
    ) -> dict[str, Any]:
        payload = {
            "tenant_id": _safe(tenant_id),
            "conversation_id": _safe(conversation_id),
            "participant_id": _safe(participant_id),
            "participant_type": participant_type,
            "participant_name": participant_name,
            "status": "online",
            "last_seen": None,
            "updated_at": _now_iso(),
        }
        key = self.presence_key(tenant_id, conversation_id, participant_id)
        if hasattr(self.redis, "incr"):
            self.redis.incr(key)
            self.redis.expire(key, PRESENCE_TTL_SECONDS)
        else:
            self.redis.setex(key, PRESENCE_TTL_SECONDS, payload["updated_at"])
        return payload

    def heartbeat(self, *, tenant_id: Any, conversation_id: Any, participant_id: Any) -> dict[str, Any]:
        key = self.presence_key(tenant_id, conversation_id, participant_id)
        timestamp = _now_iso()
        if self.redis.exists(key) and hasattr(self.redis, "expire"):
            self.redis.expire(key, PRESENCE_TTL_SECONDS)
        else:
            self.redis.setex(key, PRESENCE_TTL_SECONDS, timestamp)
        return {
            "tenant_id": _safe(tenant_id),
            "conversation_id": _safe(conversation_id),
            "participant_id": _safe(participant_id),
            "status": "online",
            "last_seen": None,
            "updated_at": timestamp,
        }

    def mark_offline(
        self,
        *,
        tenant_id: Any,
        conversation_id: Any,
        participant_id: Any,
        participant_type: str = "agent",
        participant_name: str | None = None,
    ) -> dict[str, Any]:
        last_seen = _now_iso()
        key = self.presence_key(tenant_id, conversation_id, participant_id)
        remaining = 0
        if hasattr(self.redis, "decr") and self.redis.exists(key):
            remaining = int(self.redis.decr(key) or 0)
            if remaining > 0:
                self.redis.expire(key, PRESENCE_TTL_SECONDS)
        if remaining <= 0:
            self.redis.delete(key)
            self.redis.set(self.last_seen_key(tenant_id, conversation_id, participant_id), last_seen)
        return {
            "tenant_id": _safe(tenant_id),
            "conversation_id": _safe(conversation_id),
            "participant_id": _safe(participant_id),
            "participant_type": participant_type,
            "participant_name": participant_name,
            "status": "online" if remaining > 0 else "offline",
            "last_seen": None if remaining > 0 else last_seen,
        }

    def get_presence(
        self,
        *,
        tenant_id: Any,
        conversation_id: Any,
        participant_id: Any,
        participant_type: str = "agent",
        participant_name: str | None = None,
    ) -> dict[str, Any]:
        is_online = bool(self.redis.exists(self.presence_key(tenant_id, conversation_id, participant_id)))
        last_seen = None if is_online else self.redis.get(self.last_seen_key(tenant_id, conversation_id, participant_id))
        return {
            "tenant_id": _safe(tenant_id),
            "conversation_id": _safe(conversation_id),
            "participant_id": _safe(participant_id),
            "participant_type": participant_type,
            "participant_name": participant_name,
            "status": "online" if is_online else "offline",
            "last_seen": last_seen,
        }

    async def publish_presence_update(self, payload: dict[str, Any]) -> None:
        event = {"type": "presence_updated", **payload}
        tenant_id = event["tenant_id"]
        conversation_id = event["conversation_id"]
        await redis_broker.publish(f"dashboard:{tenant_id}", event)
        await redis_broker.publish(f"{tenant_id}:{conversation_id}", event)

    def typing_start(
        self,
        *,
        tenant_id: Any,
        conversation_id: Any,
        participant_id: Any,
        participant_type: str = "agent",
        participant_name: str | None = None,
    ) -> dict[str, Any]:
        self.redis.setex(self.typing_key(tenant_id, conversation_id, participant_id), TYPING_TTL_SECONDS, _now_iso())
        return self.typing_payload(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            participant_id=participant_id,
            participant_type=participant_type,
            participant_name=participant_name,
            is_typing=True,
        )

    def typing_stop(
        self,
        *,
        tenant_id: Any,
        conversation_id: Any,
        participant_id: Any,
        participant_type: str = "agent",
        participant_name: str | None = None,
    ) -> dict[str, Any]:
        self.redis.delete(self.typing_key(tenant_id, conversation_id, participant_id))
        return self.typing_payload(
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            participant_id=participant_id,
            participant_type=participant_type,
            participant_name=participant_name,
            is_typing=False,
        )

    def typing_payload(
        self,
        *,
        tenant_id: Any,
        conversation_id: Any,
        participant_id: Any,
        participant_type: str,
        participant_name: str | None,
        is_typing: bool,
    ) -> dict[str, Any]:
        return {
            "type": "typing",
            "tenant_id": _safe(tenant_id),
            "conversation_id": _safe(conversation_id),
            "participant_id": _safe(participant_id),
            "participant_type": participant_type,
            "participant_name": participant_name,
            "is_typing": is_typing,
        }

    async def publish_typing_update(self, payload: dict[str, Any]) -> None:
        await redis_broker.publish(f"{payload['tenant_id']}:{payload['conversation_id']}", payload)
