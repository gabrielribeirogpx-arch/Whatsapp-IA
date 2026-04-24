from __future__ import annotations

import logging
import os

from redis import Redis
from rq import Connection, Worker

from app.services.queue import SEND_QUEUE_NAME

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("rq-worker")


def main() -> None:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    redis_conn = Redis.from_url(redis_url, decode_responses=True)
    logger.info("RQ worker iniciado redis=%s queue=%s", redis_url, SEND_QUEUE_NAME)

    with Connection(redis_conn):
        worker = Worker([SEND_QUEUE_NAME])
        worker.work(with_scheduler=True)


if __name__ == "__main__":
    main()
