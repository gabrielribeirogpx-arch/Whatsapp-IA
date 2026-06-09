from app.services.redis_realtime_service import redis_broker as sse_broker

async def publish_dashboard_event(*, tenant_id, payload: dict) -> None:
    """Publish tenant-wide dashboard/inbox realtime events through the shared Redis broker."""
    await sse_broker.publish(f"dashboard:{tenant_id}", payload)

def publish_contact_event(*, tenant_id, contact_id, event) -> None:
    """Best-effort publish of CRM timeline events to Redis subscribers."""
    payload = {
        "id": str(getattr(event, "id", "")),
        "type": getattr(event, "type", ""),
        "title": getattr(event, "title", ""),
        "description": getattr(event, "description", None),
        "metadata_json": getattr(event, "metadata_json", None) or {},
        "created_at": getattr(event, "created_at", None).isoformat() if getattr(event, "created_at", None) else None,
    }
    channel = f"crm:{tenant_id}:{contact_id}"
    
    # Executa em background para não bloquear o fluxo principal
    import asyncio
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
    loop.create_task(sse_broker.publish(channel, payload))

def sync_publish(channel: str, payload: dict) -> None:
    """Interface síncrona para workers."""
    sse_broker.sync_publish(channel, payload)
