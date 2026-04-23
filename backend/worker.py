from __future__ import annotations

import json
import logging
import time
import uuid

from app.core.redis_client import get_redis_client
from app.db.session import SessionLocal
from app.services.delay_queue_service import DELAY_ZSET_KEY
from app.services.flow_engine_service import process_flow_engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def run_worker_loop() -> None:
    redis_client = get_redis_client()

    while True:
        now = int(time.time())
        jobs = redis_client.zrangebyscore(DELAY_ZSET_KEY, min=0, max=now)

        for raw_job in jobs:
            try:
                payload = json.loads(raw_job)
                tenant_id = uuid.UUID(payload["tenant_id"])
                phone = str(payload["phone"])
                next_node_id = uuid.UUID(payload["next_node_id"])

                with SessionLocal() as db:
                    logger.info(
                        "Job de delay executado tenant_id=%s phone=%s next_node_id=%s",
                        tenant_id,
                        phone,
                        next_node_id,
                    )
                    process_flow_engine(
                        db=db,
                        tenant_id=tenant_id,
                        phone=phone,
                        force_node=next_node_id,
                    )
                    db.commit()

                redis_client.zrem(DELAY_ZSET_KEY, raw_job)
            except Exception:
                logger.exception("Falha ao processar job de delay payload=%s", raw_job)

        time.sleep(1)


if __name__ == "__main__":
    run_worker_loop()
