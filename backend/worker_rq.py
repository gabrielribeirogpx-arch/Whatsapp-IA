from rq import Worker, Queue, Connection
from redis import Redis
import os

redis_url = os.getenv("REDIS_URL")

if not redis_url:
    raise Exception("REDIS_URL não configurado")

conn = Redis.from_url(redis_url)

listen = ["default"]

if __name__ == "__main__":
    print("[RQ WORKER] started")
    with Connection(conn):
        worker = Worker(list(map(Queue, listen)))
        worker.work()
