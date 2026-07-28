from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")

from app.api import whatsapp


class _Request:
    pass


def test_legacy_provider_webhook_forwards_interactive_payload_to_canonical_ingress(monkeypatch):
    request = _Request()
    received = []

    async def _enqueue(candidate):
        received.append(candidate)
        return True, "wamid.button"

    monkeypatch.setattr(whatsapp, "enqueue_webhook_payload", _enqueue)

    response = asyncio.run(whatsapp.receive_message(request))

    assert received == [request]
    assert response == {"status": "queued"}


def test_legacy_provider_webhook_acknowledges_payload_rejected_by_ingress(monkeypatch):
    async def _enqueue(_request):
        return False, None

    monkeypatch.setattr(whatsapp, "enqueue_webhook_payload", _enqueue)

    response = asyncio.run(whatsapp.receive_message(_Request()))

    assert response == {"status": "accepted"}
