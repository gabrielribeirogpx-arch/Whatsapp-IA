import os
import subprocess

import redis
from rq import Connection, Queue, Worker

from app.core.startup_checks import (
    WORKER_REQUIRED_DEPENDENCIES,
    verify_alembic_at_head,
    verify_required_dependencies,
    verify_required_env_vars,
    verify_runtime_secrets,
    wait_for_database,
)
from app.db.session import dispose_engine_connections_after_fork

DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")


def run_startup_checks() -> redis.Redis:
    print("[WORKER] Running startup checks...")
    verify_required_env_vars("DATABASE_URL", "REDIS_URL")
    verify_required_dependencies(WORKER_REQUIRED_DEPENDENCIES)
    verify_runtime_secrets()
    wait_for_database()
    verify_alembic_at_head()

    print("[WORKER] Connecting Redis...")
    redis_conn = redis.from_url(str(os.getenv("REDIS_URL")))
    redis_conn.ping()
    print("[WORKER] Startup checks passed")
    return redis_conn


def runtime_commit_sha() -> str:
    for env_name in (
        "WORKER_COMMIT",
        "API_COMMIT",
        "GIT_COMMIT",
        "RENDER_GIT_COMMIT",
        "RAILWAY_GIT_COMMIT_SHA",
        "VERCEL_GIT_COMMIT_SHA",
        "HEROKU_SLUG_COMMIT",
        "SOURCE_VERSION",
        "COMMIT_SHA",
    ):
        commit = str(os.getenv(env_name) or "").strip()
        if commit:
            return commit

    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except Exception:
        return "unknown"

    return completed.stdout.strip() or "unknown"


listen = [
    os.getenv("INCOMING_MESSAGE_QUEUE", "high_priority"),
    os.getenv("WHATSAPP_SEND_QUEUE", "normal"),
    os.getenv("LOW_PRIORITY_QUEUE", "low"),
]


class LoggingWorker(Worker):
    def execute_job(self, job, queue):
        print(f"[RQ JOB START] {job.id}")
        try:
            result = super().execute_job(job, queue)
            print(f"[RQ JOB SUCCESS] {job.id}")
            return result
        except Exception as e:
            print(f"[RQ JOB ERROR] {job.id}: {e}")
            raise


if __name__ == "__main__":
    print(f"[RQ WORKER] starting commit_sha={runtime_commit_sha()} queues={','.join(listen)}")
    conn = run_startup_checks()
    dispose_engine_connections_after_fork()
    print(f"[RQ WORKER] started commit_sha={runtime_commit_sha()} queues={','.join(listen)}")
    with Connection(conn):
        worker = LoggingWorker(list(map(Queue, listen)))
        worker.work()
