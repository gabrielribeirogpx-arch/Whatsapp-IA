from __future__ import annotations

import uuid

from app.services.embedding_service import cosine_similarity
from app.services import llm_service


class _EmptyResult:
    def scalars(self):
        return self

    def first(self):
        return None


class _EmptyDB:
    def execute(self, statement):
        return _EmptyResult()


def test_resolve_tenant_config_uses_defaults_when_rag_options_are_none(monkeypatch):
    monkeypatch.setenv("AI_PROVIDER", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.delenv("AI_TEMPERATURE", raising=False)
    monkeypatch.delenv("AI_MAX_TOKENS", raising=False)

    config = llm_service._resolve_tenant_config(
        _EmptyDB(),
        uuid.uuid4(),
        options={"temperature": None, "max_tokens": None},
    )

    assert config["temperature"] == llm_service.DEFAULT_TEMPERATURE
    assert config["max_tokens"] == llm_service.DEFAULT_MAX_TOKENS


def test_cosine_similarity_treats_none_vector_values_as_zero():
    assert cosine_similarity([None, 1.0], [1.0, 1.0]) > 0
