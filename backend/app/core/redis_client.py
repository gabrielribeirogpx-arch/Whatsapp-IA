import os

from redis import Redis


REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

_redis_client: Redis | None = None


def get_redis_client() -> Redis:
    global _redis_client
    if _redis_client is None:
        _redis_client = Redis.from_url(REDIS_URL, decode_responses=True)
    return _redis_client
