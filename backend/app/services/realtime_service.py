import asyncio
import json
from collections import defaultdict


class SSEBroker:
    def __init__(self) -> None:
        self._queues: defaultdict[str, set[asyncio.Queue[str]]] = defaultdict(set)

    async def subscribe(self, phone: str) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._queues[phone].add(queue)
        return queue

    def unsubscribe(self, phone: str, queue: asyncio.Queue[str]) -> None:
        if phone in self._queues:
            self._queues[phone].discard(queue)
            if not self._queues[phone]:
                del self._queues[phone]

    async def publish(self, phone: str, payload: dict) -> None:
        data = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        for queue in list(self._queues.get(phone, set())):
            await queue.put(data)


sse_broker = SSEBroker()
