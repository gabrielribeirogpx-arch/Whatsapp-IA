from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from time import time

from redis.asyncio import Redis

from app.core.startup_checks import (
    WORKER_REQUIRED_DEPENDENCIES,
    validate_oauth_encryption_key,
    verify_alembic_at_head,
    verify_required_dependencies,
    verify_required_env_vars,
    verify_runtime_secrets,
    wait_for_database,
)
from app.db.session import SessionLocal, dispose_engine_connections_after_fork
from app.flow_v2.delay_worker import FlowV2DelayWorker
from app.services.delay_queue_service import DELAY_ZSET_KEY
from app.services.flow_engine_service import process_flow_engine
from app.services.dead_letter_service import record_dead_letter
from app.services.job_queue_service import build_version

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
    def __init__(
        self,
        redis_url: str,
        poll_interval_seconds: float = 1.0,
        *,
        flow_v2_delay_worker: FlowV2DelayWorker | None = None,
    ) -> None:
        self.redis_url = redis_url
        self.poll_interval_seconds = poll_interval_seconds
        self.redis: Redis = Redis.from_url(redis_url, decode_responses=True)
        self.flow_v2_delay_worker = flow_v2_delay_worker or FlowV2DelayWorker()
        self._stop_event = asyncio.Event()
        self.graceful_shutdown_seconds = int(os.getenv("WORKER_GRACEFUL_SHUTDOWN_SECONDS", "30"))

    @staticmethod
    def reset_db_connections() -> None:
        # Railway/Switchback can close idle Postgres sockets, and worker
        # processes may inherit pools across forks. Start each delay-worker
        # process with an empty pool so the first poll of
        # flow_v2_scheduled_jobs opens a fresh connection.
        dispose_engine_connections_after_fork()

    async def start(self) -> None:
        self._register_signal_handlers()
        logger.info(
            "event=delay_worker_started build_version=%s redis=%s zset=%s v2_table=%s",
            build_version(),
            self.redis_url,
            DELAY_ZSET_KEY,
            "flow_v2_scheduled_jobs",
        )

        try:
            while not self._stop_event.is_set():
                await self._process_due_jobs_once()
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self.poll_interval_seconds)
                except asyncio.TimeoutError:
                    pass
        finally:
            await self.redis.aclose()
            logger.info("event=worker_drain_finished worker=delay")

    def stop(self) -> None:
        logger.info("event=worker_drain_started worker=delay deadline_seconds=%s", self.graceful_shutdown_seconds)
        self._stop_event.set()

    def _register_signal_handlers(self) -> None:
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, self.stop)
            except NotImplementedError:
                logger.warning("Signal handler não suportado para %s neste ambiente", sig)

    async def _process_due_jobs_once(self) -> None:
        try:
            processed_v2 = await asyncio.to_thread(self._process_flow_v2_due_jobs_once)
            if processed_v2:
                logger.info("Runtime V2 delay jobs processados count=%s backend=flow_v2_scheduled_jobs", processed_v2)
        except Exception:
            logger.exception("Falha ao processar delays Runtime V2 em flow_v2_scheduled_jobs")

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
                record_dead_letter("delay", None, None, "invalid_delay_payload", {"raw_length": len(str(raw_job))}, {})
                logger.exception("Payload inválido removido da fila")
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
                record_dead_letter("delay", job.tenant_id, None, "delay_job_failed", {"phone": job.phone, "next_node_id": str(job.next_node_id)}, {})
                logger.exception(
                    "Falha ao executar job, reinserindo na fila tenant_id=%s phone=%s next_node_id=%s",
                    job.tenant_id,
                    job.phone,
                    job.next_node_id,
                )
                await self.redis.zadd(DELAY_ZSET_KEY, {raw_job: now + 1})

    def _process_flow_v2_due_jobs_once(self) -> int:
        with SessionLocal() as db:
            try:
                result = self.flow_v2_delay_worker.run_due(
                    db,
                    now=datetime.now(UTC).replace(tzinfo=None),
                )
                db.commit()
                return result.processed
            except Exception:
                db.rollback()
                raise

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


async def verify_redis(redis_url: str) -> None:
    redis_client = Redis.from_url(redis_url, decode_responses=True)
    try:
        await redis_client.ping()
    finally:
        await redis_client.aclose()


async def run_startup_checks() -> str:
    logger.info("event=delay_worker_startup_checks_start")
    verify_required_env_vars("DATABASE_URL", "REDIS_URL")
    verify_required_dependencies(WORKER_REQUIRED_DEPENDENCIES)
    verify_runtime_secrets()
    validate_oauth_encryption_key()
    wait_for_database()
    verify_alembic_at_head()
    redis_url = str(os.getenv("REDIS_URL"))
    await verify_redis(redis_url)
    logger.info("event=delay_worker_startup_checks_passed build_version=%s", build_version())
    return redis_url


async def main() -> None:
    redis_url = await run_startup_checks()
    DelayWorker.reset_db_connections()
    worker = DelayWorker(redis_url=redis_url, poll_interval_seconds=1.0)
    await worker.start()


if __name__ == "__main__":
    asyncio.run(main())
