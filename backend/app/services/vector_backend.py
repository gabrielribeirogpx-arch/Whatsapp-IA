from __future__ import annotations

import logging
from typing import Any, Protocol

from sqlalchemy.orm import Session

from app.services.embedding_service import cosine_similarity, generate_embedding_for_tenant

logger = logging.getLogger(__name__)


class VectorBackend(Protocol):
    def embed_text(self, tenant_id, text: str, options: dict[str, Any] | None = None) -> list[float]: ...
    def similarity(self, a: list[float] | None, b: list[float] | None) -> float: ...
    def search_vectors(self, query_embedding: list[float], candidate_vectors: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]: ...


class JsonEmbeddingBackend:
    """JSON embedding backend compatible with current RAG storage.

    TODO: Add PgVectorBackend without changing service contracts.
    TODO: Add QdrantBackend behind this same interface for external vector stores.
    """

    name = "json_embedding"

    def __init__(self, db: Session):
        self.db = db

    def embed_text(self, tenant_id, text: str, options: dict[str, Any] | None = None) -> list[float]:
        return generate_embedding_for_tenant(self.db, tenant_id, str(text or '')[:8000], **(options or {}))

    def similarity(self, a: list[float] | None, b: list[float] | None) -> float:
        return float(cosine_similarity(a, b))

    def search_vectors(self, query_embedding: list[float], candidate_vectors: list[dict[str, Any]], top_k: int) -> list[dict[str, Any]]:
        ranked = []
        for item in candidate_vectors:
            score = self.similarity(query_embedding, item.get('embedding'))
            ranked.append({**item, 'score': score})
        return sorted(ranked, key=lambda x: x.get('score', 0), reverse=True)[: max(1, int(top_k or 5))]
