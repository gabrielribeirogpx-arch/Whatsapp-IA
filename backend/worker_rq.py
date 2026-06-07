import os
import subprocess

import redis
from rq import Connection, Queue, Worker

from app.db.session import dispose_engine_connections_after_fork

DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")

if not DATABASE_URL:
    raise Exception("DATABASE_URL não configurado")

if not REDIS_URL:
    raise Exception("REDIS_URL não configurado")

print("[WORKER] DB engine configured with pooled connection health checks")

print("[WORKER] Connecting Redis...")
conn = redis.from_url(REDIS_URL)


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
    print(f"[RQ WORKER] started commit_sha={runtime_commit_sha()} queues={','.join(listen)}")
    dispose_engine_connections_after_fork()
    with Connection(conn):
        worker = LoggingWorker(list(map(Queue, listen)))
        worker.work()
