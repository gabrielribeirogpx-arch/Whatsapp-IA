from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import uuid
from dataclasses import dataclass
from time import time

from redis.asyncio import Redis

from app.db.session import SessionLocal
from app.services.delay_queue_service import DELAY_ZSET_KEY
from app.services.flow_engine_service import process_flow_engine

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("delay-worker")


@dataclass(frozen=True)
class DelayJob:
    tenant_id: uuid.UUID
    phone: str
    next_node_id: uuid.UUID

    @classmethod
    def from_raw(cls, raw_job: str) -> "DelayJob":
        payload = json.loads(raw_job)
        return cls(
            tenant_id=uuid.UUID(str(payload["tenant_id"])),
            phone=str(payload["phone"]),
            next_node_id=uuid.UUID(str(payload["next_node_id"])),
        )


class DelayWorker:
    def __init__(self, redis_url: str, poll_interval_seconds: float = 1.0) -> None:
        self.redis_url = redis_url
        self.poll_interval_seconds = poll_interval_seconds
        self.redis: Redis = Redis.from_url(redis_url, decode_responses=True)
        self._stop_event = asyncio.Event()

    async def start(self) -> None:
        self._register_signal_handlers()
        logger.info("Delay worker iniciado. redis=%s zset=%s", self.redis_url, DELAY_ZSET_KEY)

        try:
            while not self._stop_event.is_set():
                await self._process_due_jobs_once()
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval_seconds)
                except asyncio.TimeoutError:
                    pass
        finally:
            await self.redis.aclose()
            logger.info("Delay worker finalizado")

    def stop(self) -> None:
        self._stop_event.set()

    def _register_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop)
            except NotImplementedError:
                logger.warning("Signal handler não suportado para %s neste ambiente", sig)

    async def _process_due_jobs_once(self) -> None:
        now = int(time())
        raw_jobs = await self.redis.zrangebyscore(DELAY_ZSET_KEY, min=0, max=now)
        if not raw_jobs:
            return

        for raw_job in raw_jobs:
            removed = await self.redis.zrem(DELAY_ZSET_KEY, raw_job)
            if removed == 0:
                continue

            try:
                job = DelayJob.from_raw(raw_job)
            except Exception:
                logger.exception("Payload inválido removido da fila: %s", raw_job)
                continue

            try:
                await asyncio.to_thread(self._run_flow_engine_job, job)
                logger.info(
                    "Job de delay processado tenant_id=%s phone=%s next_node_id=%s",
                    job.tenant_id,
                    job.phone,
                    job.next_node_id,
                )
            except Exception:
                logger.exception(
                    "Falha ao executar job, reinserindo na fila tenant_id=%s phone=%s next_node_id=%s",
                    job.tenant_id,
                    job.phone,
                    job.next_node_id,
                )
                await self.redis.zadd(DELAY_ZSET_KEY, {raw_job: now + 1})

    @staticmethod
    def _run_flow_engine_job(job: DelayJob) -> None:
        with SessionLocal() as db:
            process_flow_engine(
                db=db,
                tenant_id=job.tenant_id,
                phone=job.phone,
                force_node=job.next_node_id,
            )
            db.commit()


async def main() -> None:
    redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    worker = DelayWorker(redis_url=redis_url, poll_interval_seconds=1.0)
    await worker.start()


if __name__ == "__main__":
    asyncio.run(main())
