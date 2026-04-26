from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.models.flow import Flow
from app.services import flow_engine_service as service


class _DBStub:
    pass


def _build_flow(*, published: uuid.UUID | None, current: uuid.UUID | None) -> Flow:
    return Flow(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        name="runtime",
        published_version_id=published,
        current_version_id=current,
    )


def _version(nodes=None, edges=None):
    return SimpleNamespace(
        id=uuid.uuid4(),
        nodes=nodes if nodes is not None else [{"id": "start", "type": "message", "data": {"isStart": True}}],
        edges=edges if edges is not None else [],
    )


def test_runtime_prefers_published_version(monkeypatch):
    published_id = uuid.uuid4()
    current_id = uuid.uuid4()
    flow = _build_flow(published=published_id, current=current_id)
    published = _version()

    monkeypatch.setattr(service, "resolve_flow", lambda **_: flow)
    monkeypatch.setattr(
        service,
        "_get_valid_flow_version_by_id",
        lambda **kwargs: published if kwargs["version_id"] == published_id else None,
    )
    monkeypatch.setattr(service, "_get_latest_valid_flow_version", lambda **_: None)

    payload = service.resolve_runtime_flow_graph(db=_DBStub(), tenant_id=flow.tenant_id, flow_id=str(flow.id))
    assert payload["source"] == "published_version"
    assert payload["version_id"] == str(published.id)
    service.invalidate_flow_runtime_cache(flow.id)


def test_runtime_fallbacks_to_latest_valid(monkeypatch):
    flow = _build_flow(published=uuid.uuid4(), current=uuid.uuid4())
    fallback = _version()

    monkeypatch.setattr(service, "resolve_flow", lambda **_: flow)
    monkeypatch.setattr(service, "_get_valid_flow_version_by_id", lambda **_: None)
    monkeypatch.setattr(service, "_get_latest_valid_flow_version", lambda **_: fallback)

    payload = service.resolve_runtime_flow_graph(db=_DBStub(), tenant_id=flow.tenant_id, flow_id=str(flow.id))
    assert payload["source"] == "latest_valid_version"
    assert payload["version_id"] == str(fallback.id)
    assert isinstance(payload["nodes"], list)
    assert isinstance(payload["edges"], list)
    service.invalidate_flow_runtime_cache(flow.id)
