import asyncio
import json
from collections import defaultdict

from fastapi import WebSocket


class SSEBroker:
    def __init__(self) -> None:
        self._queues: defaultdict[str, set[asyncio.Queue[str]]] = defaultdict(set)
        self._websockets: defaultdict[str, set[WebSocket]] = defaultdict(set)

    async def subscribe(self, phone: str) -> asyncio.Queue[str]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        self._queues[phone].add(queue)
        return queue

    def unsubscribe(self, phone: str, queue: asyncio.Queue[str]) -> None:
        if phone in self._queues:
            self._queues[phone].discard(queue)
            if not self._queues[phone]:
                del self._queues[phone]

    async def subscribe_websocket(self, channel: str, websocket: WebSocket) -> None:
        self._websockets[channel].add(websocket)

    def unsubscribe_websocket(self, channel: str, websocket: WebSocket) -> None:
        if channel in self._websockets:
            self._websockets[channel].discard(websocket)
            if not self._websockets[channel]:
                del self._websockets[channel]

    async def publish(self, phone: str, payload: dict) -> None:
        data = f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
        for queue in list(self._queues.get(phone, set())):
            await queue.put(data)

        dead_websockets: list[WebSocket] = []
        for websocket in list(self._websockets.get(phone, set())):
            try:
                await websocket.send_json(payload)
            except Exception:
                dead_websockets.append(websocket)

        for websocket in dead_websockets:
            self.unsubscribe_websocket(phone, websocket)


sse_broker = SSEBroker()


async def publish_dashboard_event(*, tenant_id, payload: dict) -> None:
    """Publish tenant-wide dashboard/inbox realtime events through the shared SSE broker."""
    await sse_broker.publish(f"dashboard:{tenant_id}", payload)


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
