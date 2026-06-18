import asyncio
import json
import logging
import os
from typing import Awaitable, Callable
from uuid import uuid4
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

    async def subscribe_websocket(
        self,
        channel: str,
        websocket: WebSocket,
        *,
        on_client_message: Callable[[dict, str], Awaitable[None]] | None = None,
    ) -> None:
        print("[REDIS SUBSCRIBE WS]", channel)
        connection_id = uuid4().hex
        pubsub = self.client.pubsub()
        await pubsub.subscribe(channel)

        async def forward_redis_messages() -> None:
            # Uso idiomático do PubSub escutando eventos
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    payload = json.loads(message['data'])
                    if payload.get("sender_connection_id") == connection_id:
                        continue
                    print("[WS SEND]", channel)
                    await websocket.send_json(payload)

        async def wait_for_websocket_disconnect() -> None:
            while True:
                raw_message = await websocket.receive_text()
                if on_client_message is None:
                    continue
                try:
                    payload = json.loads(raw_message)
                except json.JSONDecodeError:
                    logger.warning("[WS INVALID JSON] channel=%s", channel)
                    continue
                await on_client_message(payload, connection_id)

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
        task = asyncio.create_task(self._listen_to_redis(channel, queue))
        setattr(queue, "_redis_realtime_task", task)
        return queue

    def unsubscribe(self, channel: str, queue: asyncio.Queue) -> None:
        """Stop the Redis -> Queue bridge created for an SSE subscriber."""
        print("[REDIS UNSUBSCRIBE SSE]", channel)
        task = getattr(queue, "_redis_realtime_task", None)
        if task is not None:
            task.cancel()

    async def _listen_to_redis(self, channel: str, queue: asyncio.Queue):
        pubsub = self.client.pubsub()
        await pubsub.subscribe(channel)
        try:
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    await queue.put(message['data'])
        except asyncio.CancelledError:
            raise
        finally:
            await pubsub.unsubscribe(channel)
            await pubsub.close()

# Singleton para compatibilidade com routers existentes
redis_broker = RedisRealtimeBroker()
