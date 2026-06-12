from app.services.presence_service import PRESENCE_TTL_SECONDS, TYPING_TTL_SECONDS, PresenceService


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.ttls = {}
        self.deleted = []

    def setex(self, key, ttl, value):
        self.values[key] = value
        self.ttls[key] = ttl
        return True

    def incr(self, key):
        self.values[key] = int(self.values.get(key, 0)) + 1
        return self.values[key]

    def decr(self, key):
        self.values[key] = int(self.values.get(key, 0)) - 1
        return self.values[key]

    def expire(self, key, ttl):
        self.ttls[key] = ttl
        return True

    def set(self, key, value):
        self.values[key] = value
        return True

    def get(self, key):
        return self.values.get(key)

    def exists(self, key):
        return int(key in self.values)

    def delete(self, key):
        self.deleted.append(key)
        existed = key in self.values
        self.values.pop(key, None)
        self.ttls.pop(key, None)
        return int(existed)


def test_mark_online_creates_presence_key_with_ttl_and_scoped_payload():
    redis = FakeRedis()
    service = PresenceService(redis)

    payload = service.mark_online(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        participant_id="agent-1",
        participant_type="agent",
        participant_name="Gabriel",
    )

    key = "presence:tenant-1:conversation-1:agent-1"
    assert key in redis.values
    assert redis.ttls[key] == PRESENCE_TTL_SECONDS
    assert payload["tenant_id"] == "tenant-1"
    assert payload["conversation_id"] == "conversation-1"
    assert payload["participant_id"] == "agent-1"
    assert payload["participant_type"] == "agent"
    assert payload["status"] == "online"


def test_heartbeat_renews_presence_ttl():
    redis = FakeRedis()
    service = PresenceService(redis)

    payload = service.heartbeat(tenant_id="tenant-1", conversation_id="conversation-1", participant_id="agent-1")

    key = "presence:tenant-1:conversation-1:agent-1"
    assert key in redis.values
    assert redis.ttls[key] == PRESENCE_TTL_SECONDS
    assert payload["tenant_id"] == "tenant-1"
    assert payload["conversation_id"] == "conversation-1"
    assert payload["status"] == "online"


def test_mark_offline_removes_key_and_sets_last_seen():
    redis = FakeRedis()
    service = PresenceService(redis)
    service.mark_online(tenant_id="tenant-1", conversation_id="conversation-1", participant_id="agent-1")

    payload = service.mark_offline(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        participant_id="agent-1",
        participant_type="agent",
    )

    assert "presence:tenant-1:conversation-1:agent-1" not in redis.values
    assert "presence:tenant-1:conversation-1:agent-1" in redis.deleted
    assert redis.get("presence:last_seen:tenant-1:conversation-1:agent-1") == payload["last_seen"]
    assert payload["tenant_id"] == "tenant-1"
    assert payload["conversation_id"] == "conversation-1"
    assert payload["status"] == "offline"
    assert payload["last_seen"]


def test_typing_start_creates_short_ttl_key_and_payload():
    redis = FakeRedis()
    service = PresenceService(redis)

    payload = service.typing_start(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        participant_id="agent-1",
        participant_type="agent",
        participant_name="Gabriel",
    )

    key = "typing:tenant-1:conversation-1:agent-1"
    assert key in redis.values
    assert redis.ttls[key] == TYPING_TTL_SECONDS
    assert payload["type"] == "typing"
    assert payload["tenant_id"] == "tenant-1"
    assert payload["conversation_id"] == "conversation-1"
    assert payload["participant_type"] == "agent"
    assert payload["participant_name"] == "Gabriel"
    assert payload["is_typing"] is True


def test_typing_stop_removes_key_and_payload_includes_scope():
    redis = FakeRedis()
    service = PresenceService(redis)
    service.typing_start(tenant_id="tenant-1", conversation_id="conversation-1", participant_id="agent-1")

    payload = service.typing_stop(
        tenant_id="tenant-1",
        conversation_id="conversation-1",
        participant_id="agent-1",
        participant_type="agent",
    )

    assert "typing:tenant-1:conversation-1:agent-1" not in redis.values
    assert "typing:tenant-1:conversation-1:agent-1" in redis.deleted
    assert payload["type"] == "typing"
    assert payload["tenant_id"] == "tenant-1"
    assert payload["conversation_id"] == "conversation-1"
    assert payload["is_typing"] is False
