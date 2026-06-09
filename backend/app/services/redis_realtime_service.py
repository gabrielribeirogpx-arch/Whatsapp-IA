import asyncio
import json
import logging
import os
import redis.asyncio as redis
from fastapi import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

class RedisRealtimeBroker:
    def __init__(self) -> None:
        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379")
        # Client assíncrono persistente
        self.client = redis.from_url(self.redis_url, decode_responses=True)

    async def publish(self, channel: str, payload: dict) -> None:
        print("[REDIS PUBLISH]", channel)
        await self.client.publish(channel, json.dumps(payload))

    async def subscribe_websocket(self, channel: str, websocket: WebSocket) -> None:
        print("[REDIS SUBSCRIBE WS]", channel)
        pubsub = self.client.pubsub()
        await pubsub.subscribe(channel)
        
        try:
            # Uso idiomático do PubSub escutando eventos
            async for message in pubsub.listen():
                if message['type'] == 'message':
                    payload = json.loads(message['data'])
                    print("[WS SEND]", channel)
                    await websocket.send_json(payload)
        except WebSocketDisconnect:
            print("[WS DISCONNECT]", channel)
        finally:
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
