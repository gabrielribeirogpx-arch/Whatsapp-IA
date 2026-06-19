from __future__ import annotations

import uuid

import pytest

from app.services import vector_store_service as vss
from app.services.vector_store_service import VectorStoreService


class DummyDb:
    def execute(self, *args, **kwargs):
        raise RuntimeError("pgvector unavailable")


def test_default_backend_is_json_embedding(monkeypatch):
    monkeypatch.delenv("VECTOR_BACKEND", raising=False)
    monkeypatch.delenv("PGVECTOR_ENABLED", raising=False)
    assert VectorStoreService(DummyDb()).get_backend() == "json_embedding"


def test_pgvector_disabled_uses_json_fallback(monkeypatch):
    monkeypatch.setenv("VECTOR_BACKEND", "pgvector")
    monkeypatch.setenv("PGVECTOR_ENABLED", "false")
    assert VectorStoreService(DummyDb()).get_backend() == "json_embedding"


def test_search_requires_tenant_id():
    with pytest.raises(ValueError):
        VectorStoreService(DummyDb()).search_similar(tenant_id=None, namespace="document", query_text="x")


def test_upsert_requires_tenant_id():
    with pytest.raises(ValueError):
        VectorStoreService(DummyDb()).upsert_embedding(tenant_id="", namespace="memory", object_id=uuid.uuid4(), content_text="x")


def test_pgvector_invalid_dimension_rejected(monkeypatch):
    monkeypatch.setenv("PGVECTOR_DIMENSION", "3")
    backend = vss.PgVectorBackend(DummyDb())
    with pytest.raises(ValueError):
        backend.search_similar(tenant_id=uuid.uuid4(), namespace="document", query_embedding=[0.1, 0.2], top_k=1)


def test_fallback_when_pgvector_unavailable(monkeypatch):
    monkeypatch.setenv("VECTOR_BACKEND", "pgvector")
    monkeypatch.setenv("PGVECTOR_ENABLED", "true")
    service = VectorStoreService(DummyDb())
    assert service.get_backend() == "json_embedding"


def test_metadata_contains_vector_backend(monkeypatch):
    tenant_id = uuid.uuid4()

    class Json(vss.JsonEmbeddingBackend):
        def search_similar(self, **kwargs):
            return [{"id": "1", "score": 0.9, "metadata": {}}]

    service = VectorStoreService(DummyDb())
    service._json = Json(DummyDb())
    result = service.search_similar(tenant_id=tenant_id, namespace="document", query_embedding=[1.0], top_k=1)
    assert result[0]["metadata"]["vector_backend"] == "json_embedding"
    assert "embedding" not in result[0]["metadata"]
