from rq import Worker, Queue, Connection
import redis
import os

redis_url = os.getenv("REDIS_URL")

if not redis_url:
    raise Exception("REDIS_URL não configurado")

conn = redis.from_url(redis_url)

listen = ["default"]


class LoggingWorker(Worker):
    def execute_job(self, job, queue):
        print("[RQ JOB] processing job")
        return super().execute_job(job, queue)


if __name__ == "__main__":
    print("[RQ WORKER] started")
    with Connection(conn):
        worker = LoggingWorker(list(map(Queue, listen)))
        worker.work()
