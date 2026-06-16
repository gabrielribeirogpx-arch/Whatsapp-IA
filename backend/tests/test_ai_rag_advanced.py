from __future__ import annotations

import uuid
from types import SimpleNamespace

from app.services import rag_service


def test_query_rewrite_disabled_returns_original(monkeypatch):
    monkeypatch.setattr(rag_service, "RAG_QUERY_REWRITE_ENABLED", False)
    assert rag_service.rewrite_query_for_retrieval(None, uuid.uuid4(), "tem valor inexequível?") == ["tem valor inexequível?"]


def test_query_rewrite_failure_falls_back_to_original(monkeypatch):
    monkeypatch.setattr(rag_service, "RAG_QUERY_REWRITE_ENABLED", True)
    monkeypatch.setattr(rag_service, "generate_answer_for_tenant", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert rag_service.rewrite_query_for_retrieval(None, uuid.uuid4(), "tem valor inexequível?") == ["tem valor inexequível?"]


def test_text_score_finds_exact_term_without_embedding():
    score = rag_service._text_score("A proposta será considerada inexequível pelo critério do edital.", "valor inexequível")
    assert score > 0


def test_hybrid_merge_combines_vector_and_text_duplicate():
    chunk_id = str(uuid.uuid4())
    merged = rag_service._merge_candidates([
        {"chunk_id": chunk_id, "content": "proposta inexequível", "vector_score": 0.8, "text_score": 0.0, "retrieval_mode": "vector", "matched_query_count": 1},
        {"chunk_id": chunk_id, "content": "proposta inexequível", "vector_score": 0.0, "text_score": 0.7, "retrieval_mode": "text", "matched_query_count": 1},
    ])
    assert len(merged) == 1
    assert merged[0]["retrieval_mode"] == "hybrid"
    assert merged[0]["vector_score"] == 0.8
    assert merged[0]["text_score"] == 0.7


def test_rerank_keeps_relevant_top_chunk(monkeypatch):
    monkeypatch.setattr(rag_service, "RAG_RERANK_ENABLED", True)
    candidates = [
        {"content": "texto genérico sem relação", "final_score": 0.4, "matched_query_count": 1},
        {"content": "valor inexequível e proposta inexequível no edital", "final_score": 0.4, "matched_query_count": 2},
    ]
    selected = rag_service._rerank_candidates(candidates, "tem valor inexequível?", ["proposta inexequível"], 1)
    assert "inexequível" in selected[0]["content"]


def test_low_score_triggers_fallback_when_configured(monkeypatch):
    context = [{"content": "x" * 120, "metadata": {}, "source_name": "kb", "score": 0.25, "final_score": 0.25, "retrieval_mode": "text"}]
    monkeypatch.setattr(rag_service, "retrieve_context", lambda *args, **kwargs: context)
    answer = rag_service.answer_with_rag(None, uuid.uuid4(), "pergunta", fallback_when_low_confidence=True)
    assert answer.found_context is False


def test_confidence_text_only_unknown_below_threshold():
    assert rag_service._confidence_level([{"retrieval_mode": "text", "final_score": 0.1}]) == "unknown"


def test_source_ids_filter_is_parsed():
    source_id = uuid.uuid4()
    assert rag_service._source_ids_from_filters({"knowledge_source_ids": [str(source_id)]}) == [source_id]
