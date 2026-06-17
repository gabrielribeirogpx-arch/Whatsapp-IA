from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

from app.services import contextual_query_service as cqs
from app.services import rag_service


def test_contains_context_reference_examples():
    assert cqs.contains_context_reference("Quais são esses documentos?") is True
    assert cqs.contains_context_reference("E o prazo?") is True
    assert cqs.contains_context_reference("E o e-mail?") is True


def test_complete_question_and_greeting_do_not_call_standalone(monkeypatch):
    called = False

    def fake_generate(*args, **kwargs):
        nonlocal called
        called = True
        return "não deveria chamar"

    monkeypatch.setattr(cqs, "generate_answer_for_tenant", fake_generate)
    tenant_id = uuid.uuid4()

    complete = cqs.generate_standalone_question(None, tenant_id, "Qual é o prazo para envio das propostas?", "Usuário: edital")
    greeting = cqs.generate_standalone_question(None, tenant_id, "olá", "Usuário: edital")

    assert complete == {"standalone_question": "Qual é o prazo para envio das propostas?", "used_history": False}
    assert greeting == {"standalone_question": "olá", "used_history": False}
    assert called is False


def test_standalone_uses_history(monkeypatch):
    monkeypatch.setattr(cqs, "generate_answer_for_tenant", lambda *args, **kwargs: "Quais são os documentos de habilitação exigidos pelo edital?")

    result = cqs.generate_standalone_question(None, uuid.uuid4(), "Quais são esses documentos?", "Usuário: Tenho que enviar documentação de habilitação?\nIA: Sim.")

    assert result["standalone_question"] == "Quais são os documentos de habilitação exigidos pelo edital?"
    assert result["used_history"] is True


def test_standalone_failure_falls_back(monkeypatch):
    monkeypatch.setattr(cqs, "generate_answer_for_tenant", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    result = cqs.generate_standalone_question(None, uuid.uuid4(), "E o prazo?", "Usuário: proposta")

    assert result == {"standalone_question": "E o prazo?", "used_history": False}


def test_standalone_cache_ttl_and_tenant_isolation():
    tenant_a = uuid.uuid4()
    tenant_b = uuid.uuid4()
    context = {}
    cqs.store_cached_standalone(context, tenant_id=tenant_a, current_question="E o prazo?", result={"standalone_question": "Qual é o prazo?", "used_history": True}, now=1000)

    assert cqs.get_cached_standalone(context, tenant_id=tenant_a, current_question="E o prazo?", now=1059)["standalone_question"] == "Qual é o prazo?"
    assert cqs.get_cached_standalone(context, tenant_id=tenant_b, current_question="E o prazo?", now=1059) is None
    assert cqs.get_cached_standalone(context, tenant_id=tenant_a, current_question="E o prazo?", now=1061) is None


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _DB:
    def __init__(self, rows):
        self._rows = rows

    def execute(self, statement):
        return _Rows(self._rows)


def test_recent_chunks_reuse_is_tenant_scoped_and_does_not_store_content():
    tenant_id = uuid.uuid4()
    other_tenant_id = uuid.uuid4()
    chunk_id = uuid.uuid4()
    source_id = uuid.uuid4()
    chunk = SimpleNamespace(
        id=chunk_id,
        tenant_id=tenant_id,
        source_id=source_id,
        source="edital.pdf",
        content="Documentos de habilitação exigidos: contrato social, certidões e declaração.",
        metadata_json={"page": 7},
    )
    db = _DB([(chunk, "edital.pdf")])
    recent = [{"chunk_id": str(chunk_id), "source_id": str(source_id), "score": 0.72, "page": 7, "source_name": "edital.pdf", "timestamp": datetime.now(timezone.utc).isoformat()}]

    results = rag_service.retrieve_recent_chunks(db, tenant_id, "documentos de habilitação", 5, recent_retrieved_chunks=recent)
    other_results = rag_service.retrieve_recent_chunks(db, other_tenant_id, "documentos de habilitação", 5, recent_retrieved_chunks=[])

    assert results
    assert results[0]["chunk_id"] == str(chunk_id)
    assert results[0]["score"] > 0.72
    assert "content" not in recent[0]
    assert other_results == []
