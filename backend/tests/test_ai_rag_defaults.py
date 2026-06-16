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


def test_rag_context_omits_source_labels_by_default():
    from app.services.rag_service import _format_context_for_prompt

    contexts = [
        {
            "source_name": "EDITAL_2026.pdf",
            "content": "Prazo de inscrição até 30 de junho.",
            "metadata": {"page": 4},
        }
    ]

    prompt_context = _format_context_for_prompt(contexts)

    assert "Prazo de inscrição" in prompt_context
    assert "Fonte:" not in prompt_context
    assert "EDITAL_2026" not in prompt_context
    assert "página" not in prompt_context.lower()


def test_rag_context_can_include_source_labels_when_enabled():
    from app.services.rag_service import _format_context_for_prompt

    contexts = [
        {
            "source_name": "EDITAL_2026.pdf",
            "content": "Prazo de inscrição até 30 de junho.",
            "metadata": {"page": 4},
        }
    ]

    prompt_context = _format_context_for_prompt(contexts, include_sources=True)

    assert "Fonte: EDITAL_2026.pdf, página 4" in prompt_context
    assert "Prazo de inscrição" in prompt_context


def test_rag_prompt_uses_whatsapp_short_style_by_default(monkeypatch):
    from app.services import rag_service

    captured = {}

    monkeypatch.setattr(
        rag_service,
        "retrieve_context",
        lambda db, tenant_id, question, top_k: [
            {
                "source_name": "lista_docs.pdf",
                "content": "Documentos necessários: RG, CPF e comprovante de residência.",
                "metadata": {"page": 2},
            }
        ],
    )

    def fake_generate(db, tenant_id, messages, options=None):
        captured["messages"] = messages
        return "Leve estes documentos:\n\n• RG\n• CPF\n• comprovante de residência"

    monkeypatch.setattr(rag_service, "generate_answer_for_tenant", fake_generate)

    answer = rag_service.answer_with_rag(None, uuid.uuid4(), "Quais documentos preciso levar?")

    system_prompt = captured["messages"][0]["content"]
    user_prompt = captured["messages"][1]["content"]
    assert answer.answer.startswith("Leve estes documentos")
    assert "FORMATO DA RESPOSTA NO WHATSAPP" in system_prompt
    assert "Use no máximo 2 a 4 parágrafos curtos." in system_prompt
    assert 'Use bullets quando listar documentos, prazos, requisitos ou passos.' in system_prompt
    assert "Não cite Fonte, arquivo, página ou chunk." in system_prompt
    assert "Fonte:" not in user_prompt
    assert "lista_docs.pdf" not in user_prompt
    assert "página" not in user_prompt.lower()


def test_rag_includes_sources_only_when_question_asks_for_source(monkeypatch):
    from app.services import rag_service

    captured = {}
    context = [
        {
            "source_name": "edital.pdf",
            "content": "A inscrição encerra em 30 de junho.",
            "metadata": {"page": 4},
        }
    ]
    monkeypatch.setattr(rag_service, "retrieve_context", lambda db, tenant_id, question, top_k: context)

    def fake_generate(db, tenant_id, messages, options=None):
        captured["messages"] = messages
        return "Está no edital, página 4."

    monkeypatch.setattr(rag_service, "generate_answer_for_tenant", fake_generate)

    rag_service.answer_with_rag(None, uuid.uuid4(), "De onde tirou?")

    user_prompt = captured["messages"][1]["content"]
    assert "Fonte: edital.pdf, página 4" in user_prompt
