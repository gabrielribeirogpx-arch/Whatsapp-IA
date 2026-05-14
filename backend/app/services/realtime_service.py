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


def publish_contact_event(*, tenant_id, contact_id, event) -> None:
    """Best-effort publish of CRM timeline events to SSE subscribers."""
    payload = {
        "id": str(getattr(event, "id", "")),
        "type": getattr(event, "type", ""),
        "title": getattr(event, "title", ""),
        "description": getattr(event, "description", None),
        "metadata_json": getattr(event, "metadata_json", None) or {},
        "created_at": getattr(event, "created_at", None).isoformat() if getattr(event, "created_at", None) else None,
    }
    channel = f"crm:{tenant_id}:{contact_id}"
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(sse_broker.publish(channel, payload))
