import asyncio
import json
import logging
import os
import redis.asyncio as redis
from fastapi import WebSocket, WebSocketDisconnect
from app.core.redis_client import get_redis_client

logger = logging.getLogger(__name__)

class RedisRealtimeBroker:
    def __init__(self) -> None:
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        # Client assíncrono para WebSockets/FastAPI
        self.client = redis.from_url(self.redis_url, decode_responses=True)
        # Client síncrono para Workers
        self.sync_client = get_redis_client()

    def sync_publish(self, channel: str, payload: dict) -> None:
        """Publique síncronamente a partir de workers."""
        print("[REDIS SYNC PUBLISH]", channel)
        self.sync_client.publish(channel, json.dumps(payload))

    async def publish(self, channel: str, payload: dict) -> None:
        print("[REDIS PUBLISH]", channel)
        await self.client.publish(channel, json.dumps(payload))

    def unsubscribe_websocket(self, channel: str, websocket: WebSocket) -> None:
        """Compatibility no-op.

        WebSocket PubSub cleanup is owned by subscribe_websocket(), which creates
        and closes the Redis pubsub object in its own finally block.
        """
        print("[REDIS UNSUBSCRIBE WS NOOP]", channel)

    async def subscribe_websocket(self, channel: str, websocket: WebSocket) -> None:
        print("[REDIS SUBSCRIBE WS]", channel)
        pubsub = self.client.pubsub()
        await pubsub.subscribe(channel)

        async def forward_redis_messages() -> None:
            # Uso idiomático do PubSub escutando eventos
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    payload = json.loads(message['data'])
                    print("[WS SEND]", channel)
                    await websocket.send_json(payload)

        async def wait_for_websocket_disconnect() -> None:
            while True:
                await websocket.receive_text()

        tasks = {
            asyncio.create_task(forward_redis_messages()),
            asyncio.create_task(wait_for_websocket_disconnect()),
        }

        try:
            done, _pending = await asyncio.wait(
                tasks,
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in done:
                exc = task.exception()
                if exc and not isinstance(exc, WebSocketDisconnect):
                    raise exc
        except WebSocketDisconnect:
            print("[WS DISCONNECT]", channel)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await pubsub.unsubscribe(channel)
            await pubsub.close()
            
    # Compatibilidade com SSE (StreamingResponse)
    async def subscribe(self, channel: str) -> asyncio.Queue:
        print("[REDIS SUBSCRIBE SSE]", channel)
        queue = asyncio.Queue()
        # Tarefa de background gerencia a ponte Redis -> Queue
        asyncio.create_task(self._listen_to_redis(channel, queue))
        return queue

    async def _listen_to_redis(self, channel: str, queue: asyncio.Queue):
        pubsub = self.client.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    await queue.put(message['data'])
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

# Singleton para compatibilidade com routers existentes
redis_broker = RedisRealtimeBroker()
