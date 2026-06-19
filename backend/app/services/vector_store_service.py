from __future__ import annotations

import hashlib
import logging
import os
import time
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.models.flow_ai_long_term_memory import FlowAILongTermMemory
from app.models.knowledge_chunk import KnowledgeChunk
from app.models.knowledge_source import KnowledgeSource
from app.services.embedding_service import cosine_similarity, generate_embedding_for_tenant, get_embedding_config_for_tenant

logger = logging.getLogger(__name__)

VectorNamespace = Literal["document", "memory"]
DEFAULT_PGVECTOR_DIMENSION = 1536


def _env_bool(name: str, default: str = "false") -> bool:
    return os.getenv(name, default).strip().lower() in {"1", "true", "yes", "on"}


def _configured_backend() -> str:
    return (os.getenv("VECTOR_BACKEND") or os.getenv("RAG_VECTOR_SEARCH_BACKEND") or "json_embedding").strip().lower() or "json_embedding"


def _dimension() -> int:
    try:
        return max(1, int(os.getenv("PGVECTOR_DIMENSION", str(DEFAULT_PGVECTOR_DIMENSION))))
    except ValueError:
        return DEFAULT_PGVECTOR_DIMENSION


def _distance() -> str:
    value = os.getenv("PGVECTOR_DISTANCE", "cosine").strip().lower()
    return value if value in {"cosine", "l2", "ip"} else "cosine"


def _hash_text(value: str) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()


def _uuid(value: Any, field_name: str = "tenant_id") -> uuid.UUID:
    if value in (None, ""):
        raise ValueError(f"{field_name} is required for vector store operations")
    return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


def _embedding_literal(embedding: list[float]) -> str:
    return "[" + ",".join(str(float(x)) for x in embedding) + "]"


@dataclass(frozen=True)
class VectorSearchResult:
    id: str
    score: float
    content: str | None = None
    metadata: dict[str, Any] | None = None


class JsonEmbeddingBackend:
    name = "json_embedding"

    def __init__(self, db: Session):
        self.db = db

    def embed_text(self, tenant_id: uuid.UUID, text_value: str) -> list[float]:
        return generate_embedding_for_tenant(self.db, tenant_id, str(text_value or "")[:8000])

    def upsert_embedding(self, *, tenant_id: uuid.UUID, namespace: VectorNamespace, object_id: Any, content_text: str, embedding: list[float] | None = None, metadata: dict[str, Any] | None = None, **_: Any) -> None:
        # Compatibility backend stores embeddings in existing JSON columns where possible.
        if namespace == "document":
            row = self.db.get(KnowledgeChunk, _uuid(object_id, "object_id"))
            if row and row.tenant_id == tenant_id:
                row.embedding_json = embedding or self.embed_text(tenant_id, content_text)
                row.metadata_json = {**(row.metadata_json or {}), **(metadata or {}), "vector_backend": self.name}
                self.db.add(row)
        elif namespace == "memory":
            row = self.db.get(FlowAILongTermMemory, _uuid(object_id, "object_id"))
            if row and row.tenant_id == tenant_id:
                row.fact_embedding_json = embedding or self.embed_text(tenant_id, content_text)
                row.metadata_json = {**(row.metadata_json or {}), **(metadata or {}), "vector_backend": self.name}
                self.db.add(row)

    def search_similar(self, *, tenant_id: uuid.UUID, namespace: VectorNamespace, query_text: str | None = None, query_embedding: list[float] | None = None, top_k: int = 5, filters: dict[str, Any] | None = None, min_score: float = 0.0) -> list[dict[str, Any]]:
        query_embedding = query_embedding or self.embed_text(tenant_id, query_text or "")
        if namespace == "document":
            stmt = select(KnowledgeChunk, KnowledgeSource.name).join(KnowledgeSource, KnowledgeChunk.source_id == KnowledgeSource.id, isouter=True).where(KnowledgeChunk.tenant_id == tenant_id, KnowledgeChunk.embedding_json.is_not(None))
            source_ids = (filters or {}).get("source_ids") or []
            if source_ids:
                stmt = stmt.where(KnowledgeChunk.source_id.in_([_uuid(x, "source_id") for x in source_ids]))
            rows = self.db.execute(stmt.limit(1000)).all()
            ranked = []
            for chunk, source_name in rows:
                score = float(cosine_similarity(chunk.embedding_json, query_embedding))
                if score >= min_score:
                    ranked.append({"id": str(chunk.id), "chunk_id": str(chunk.id), "content": chunk.content, "score": score, "source_id": str(chunk.source_id or ""), "source_name": source_name or chunk.source, "metadata": chunk.metadata_json or {}, "vector_backend": self.name})
            return sorted(ranked, key=lambda x: x["score"], reverse=True)[: max(1, int(top_k or 5))]
        stmt = select(FlowAILongTermMemory).where(FlowAILongTermMemory.tenant_id == tenant_id, FlowAILongTermMemory.fact_embedding_json.is_not(None))
        if (filters or {}).get("contact_id"):
            stmt = stmt.where(FlowAILongTermMemory.contact_id == _uuid(filters["contact_id"], "contact_id"))
        rows = self.db.execute(stmt.limit(500)).scalars().all()
        ranked = []
        for row in rows:
            score = float(cosine_similarity(row.fact_embedding_json, query_embedding))
            if score >= min_score:
                ranked.append({"id": str(row.id), "memory_id": str(row.id), "content": row.fact_text, "score": score, "metadata": row.metadata_json or {}, "vector_backend": self.name})
        return sorted(ranked, key=lambda x: x["score"], reverse=True)[: max(1, int(top_k or 5))]

    def delete_embeddings(self, *, tenant_id: uuid.UUID, namespace: VectorNamespace, object_ids: list[Any] | None = None, filters: dict[str, Any] | None = None) -> int:
        return 0

    def health_check(self) -> dict[str, Any]:
        return {"ok": True, "backend": self.name}


class PgVectorBackend(JsonEmbeddingBackend):
    name = "pgvector"

    def health_check(self) -> dict[str, Any]:
        try:
            self.db.execute(text("SELECT 1 FROM pg_extension WHERE extname = 'vector'"))
            return {"ok": True, "backend": self.name, "dimension": _dimension(), "distance": _distance()}
        except Exception as exc:
            return {"ok": False, "backend": self.name, "error_code": type(exc).__name__}

    def upsert_embedding(self, *, tenant_id: uuid.UUID, namespace: VectorNamespace, object_id: Any, content_text: str, embedding: list[float] | None = None, metadata: dict[str, Any] | None = None, **kwargs: Any) -> None:
        embedding = embedding or self.embed_text(tenant_id, content_text)
        if len(embedding or []) != _dimension():
            raise ValueError(f"invalid embedding dimension: expected {_dimension()}, got {len(embedding or [])}")
        model = (metadata or {}).get("embedding_model") or get_embedding_config_for_tenant(self.db, tenant_id).get("model")
        table = "document_chunk_embeddings" if namespace == "document" else "long_term_memory_embeddings"
        id_col = "chunk_id" if namespace == "document" else "memory_id"
        sql = text(f"""
            INSERT INTO {table} (id, tenant_id, {id_col}, content_hash, {('content_text' if namespace == 'document' else 'memory_text')}, embedding, embedding_model, metadata, importance_score)
            VALUES (:id, :tenant_id, :object_id, :content_hash, :content_text, CAST(:embedding AS vector), :model, CAST(:metadata AS jsonb), :importance_score)
        """)
        self.db.execute(sql, {"id": str(uuid.uuid4()), "tenant_id": str(tenant_id), "object_id": str(object_id), "content_hash": _hash_text(content_text), "content_text": content_text, "embedding": _embedding_literal(embedding), "model": model, "metadata": __import__('json').dumps(metadata or {}), "importance_score": kwargs.get("importance_score")})

    def search_similar(self, *, tenant_id: uuid.UUID, namespace: VectorNamespace, query_text: str | None = None, query_embedding: list[float] | None = None, top_k: int = 5, filters: dict[str, Any] | None = None, min_score: float = 0.0) -> list[dict[str, Any]]:
        query_embedding = query_embedding or self.embed_text(tenant_id, query_text or "")
        if len(query_embedding or []) != _dimension():
            raise ValueError(f"invalid embedding dimension: expected {_dimension()}, got {len(query_embedding or [])}")
        if namespace == "document":
            source_filter = ""
            params: dict[str, Any] = {"tenant_id": str(tenant_id), "embedding": _embedding_literal(query_embedding), "limit": max(1, int(top_k or 5)), "min_score": float(min_score)}
            if (filters or {}).get("source_ids"):
                source_filter = "AND source_id = ANY(:source_ids)"
                params["source_ids"] = [str(_uuid(x, "source_id")) for x in filters["source_ids"]]
            rows = self.db.execute(text(f"SELECT id, chunk_id, source_id, content_text, metadata, 1 - (embedding <=> CAST(:embedding AS vector)) AS score FROM document_chunk_embeddings WHERE tenant_id = :tenant_id {source_filter} AND 1 - (embedding <=> CAST(:embedding AS vector)) >= :min_score ORDER BY embedding <=> CAST(:embedding AS vector) LIMIT :limit"), params).mappings().all()
            return [{"id": str(r["id"]), "chunk_id": str(r["chunk_id"]), "source_id": str(r.get("source_id") or ""), "content": r.get("content_text"), "score": float(r["score"]), "metadata": dict(r.get("metadata") or {}), "vector_backend": self.name} for r in rows]
        params = {"tenant_id": str(tenant_id), "embedding": _embedding_literal(query_embedding), "limit": max(1, int(top_k or 5)), "min_score": float(min_score)}
        contact_filter = ""
        if (filters or {}).get("contact_id"):
            contact_filter = "AND contact_id = :contact_id"
            params["contact_id"] = str(_uuid(filters["contact_id"], "contact_id"))
        rows = self.db.execute(text(f"SELECT id, memory_id, memory_text, metadata, 1 - (embedding <=> CAST(:embedding AS vector)) AS score FROM long_term_memory_embeddings WHERE tenant_id = :tenant_id {contact_filter} AND 1 - (embedding <=> CAST(:embedding AS vector)) >= :min_score ORDER BY embedding <=> CAST(:embedding AS vector) LIMIT :limit"), params).mappings().all()
        return [{"id": str(r["id"]), "memory_id": str(r.get("memory_id") or r["id"]), "content": r.get("memory_text"), "score": float(r["score"]), "metadata": dict(r.get("metadata") or {}), "vector_backend": self.name} for r in rows]

    def delete_embeddings(self, *, tenant_id: uuid.UUID, namespace: VectorNamespace, object_ids: list[Any] | None = None, filters: dict[str, Any] | None = None) -> int:
        table = "document_chunk_embeddings" if namespace == "document" else "long_term_memory_embeddings"
        id_col = "chunk_id" if namespace == "document" else "memory_id"
        sql = f"DELETE FROM {table} WHERE tenant_id = :tenant_id"
        params = {"tenant_id": str(tenant_id)}
        if object_ids:
            sql += f" AND {id_col} = ANY(:object_ids)"
            params["object_ids"] = [str(x) for x in object_ids]
        result = self.db.execute(text(sql), params)
        return int(result.rowcount or 0)


class VectorStoreService:
    def __init__(self, db: Session):
        self.db = db
        self._json = JsonEmbeddingBackend(db)
        self._pg = PgVectorBackend(db)

    def supports_pgvector(self) -> bool:
        return _env_bool("PGVECTOR_ENABLED") and self._pg.health_check().get("ok") is True

    def get_backend(self) -> str:
        return "pgvector" if _configured_backend() == "pgvector" and self.supports_pgvector() else "json_embedding"

    def _backend(self):
        return self._pg if self.get_backend() == "pgvector" else self._json

    def upsert_embedding(self, *, tenant_id: Any, namespace: VectorNamespace, object_id: Any, content_text: str, embedding: list[float] | None = None, metadata: dict[str, Any] | None = None, **kwargs: Any) -> dict[str, Any]:
        tenant = _uuid(tenant_id)
        start = time.monotonic()
        backend = self._backend()
        try:
            backend.upsert_embedding(tenant_id=tenant, namespace=namespace, object_id=object_id, content_text=content_text, embedding=embedding, metadata=metadata, **kwargs)
            logger.info("event=vector_store_upsert tenant_id=%s backend=%s dimension=%s model=%s duration_ms=%s fallback_used=false", tenant, backend.name, len(embedding or []), (metadata or {}).get("embedding_model"), int((time.monotonic() - start) * 1000))
            return {"backend": backend.name, "fallback_used": False}
        except Exception as exc:
            if backend.name == "pgvector":
                logger.warning("event=vector_store_fallback tenant_id=%s backend=pgvector error_code=%s", tenant, type(exc).__name__)
                self._json.upsert_embedding(tenant_id=tenant, namespace=namespace, object_id=object_id, content_text=content_text, embedding=embedding, metadata=metadata, **kwargs)
                return {"backend": self._json.name, "fallback_used": True, "error_code": type(exc).__name__}
            raise

    def search_similar(self, *, tenant_id: Any, namespace: VectorNamespace, query_text: str | None = None, query_embedding: list[float] | None = None, top_k: int = 5, filters: dict[str, Any] | None = None, min_score: float = 0.0) -> list[dict[str, Any]]:
        tenant = _uuid(tenant_id)
        start = time.monotonic()
        backend = self._backend()
        fallback = False
        try:
            results = backend.search_similar(tenant_id=tenant, namespace=namespace, query_text=query_text, query_embedding=query_embedding, top_k=top_k, filters=filters, min_score=min_score)
        except Exception as exc:
            if backend.name != "pgvector":
                logger.error("event=vector_store_error tenant_id=%s backend=%s error_code=%s", tenant, backend.name, type(exc).__name__)
                raise
            logger.warning("event=vector_store_fallback tenant_id=%s backend=pgvector error_code=%s", tenant, type(exc).__name__)
            fallback = True
            backend = self._json
            results = backend.search_similar(tenant_id=tenant, namespace=namespace, query_text=query_text, query_embedding=query_embedding, top_k=top_k, filters=filters, min_score=min_score)
        for item in results:
            item.setdefault("metadata", {})
            item["metadata"] = {**(item.get("metadata") or {}), "vector_backend": backend.name, "vector_index_used": backend.name == "pgvector", "vector_distance": _distance(), "vector_dimension": _dimension(), "fallback_used": fallback}
            item["vector_backend"] = backend.name
        logger.info("event=vector_store_search tenant_id=%s backend=%s dimension=%s duration_ms=%s results_count=%s fallback_used=%s", tenant, backend.name, len(query_embedding or []), int((time.monotonic() - start) * 1000), len(results), fallback)
        return results

    def delete_embeddings(self, *, tenant_id: Any, namespace: VectorNamespace, object_ids: list[Any] | None = None, filters: dict[str, Any] | None = None) -> int:
        return self._backend().delete_embeddings(tenant_id=_uuid(tenant_id), namespace=namespace, object_ids=object_ids, filters=filters)

    def health_check(self) -> dict[str, Any]:
        return {"backend": self.get_backend(), "pgvector": self._pg.health_check(), "json_embedding": self._json.health_check()}
