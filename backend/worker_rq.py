import os

import redis
from rq import Connection, Queue, Worker
from sqlalchemy import create_engine

DATABASE_URL = os.getenv("DATABASE_URL")
REDIS_URL = os.getenv("REDIS_URL")

if not DATABASE_URL:
    raise Exception("DATABASE_URL não configurado")

if not REDIS_URL:
    raise Exception("REDIS_URL não configurado")

print("[WORKER] Connecting DB...")
engine = create_engine(DATABASE_URL)

print("[WORKER] Connecting Redis...")
conn = redis.from_url(REDIS_URL)

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
    print("[RQ WORKER] started")
    with Connection(conn):
        worker = LoggingWorker(list(map(Queue, listen)))
        worker.work()
