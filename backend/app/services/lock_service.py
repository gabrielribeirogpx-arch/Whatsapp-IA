import time


class ConversationLock:
    def __init__(self, redis_client):
        self.redis = redis_client

    def acquire(self, key: str, ttl: int = 10):
        return self.redis.set(key, "1", nx=True, ex=ttl)

    def release(self, key: str):
        self.redis.delete(key)
