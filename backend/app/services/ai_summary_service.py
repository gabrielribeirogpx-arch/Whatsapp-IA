from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from sqlalchemy.orm import Session

from app.services.llm_service import LLMConfigurationError, LLMGenerationError, generate_answer_for_tenant

logger = logging.getLogger(__name__)

SUPPORTED_SUMMARY_FORMATS = {"short", "detailed", "bullet_points", "handoff"}


class AISummaryError(RuntimeError):
    """Controlled error raised when an AI summary cannot be generated."""


_MARKDOWN_FENCE_RE = re.compile(r"^\s*```(?:text|markdown)?\s*|\s*```\s*$", re.IGNORECASE | re.MULTILINE)


def _clean_text(value: str) -> str:
    return _MARKDOWN_FENCE_RE.sub("", str(value or "")).strip()


def _format_instruction(summary_format: str) -> str:
    if summary_format == "short":
        return "Gere um resumo curto em 2 a 4 frases, objetivo e fiel ao conteúdo."
    if summary_format == "detailed":
        return "Gere um resumo detalhado, organizado em parágrafos curtos, incluindo fatos, decisões e contexto relevante."
    if summary_format == "bullet_points":
        return "Gere o resumo em tópicos objetivos. Inclua somente informações presentes no texto."
    return (
        "Gere exatamente uma estrutura de passagem para atendimento humano neste formato:\n\n"
        "Resumo do atendimento:\n...\n\n"
        "Dados identificados:\n"
        "- Nome:\n"
        "- Telefone:\n"
        "- Interesse:\n"
        "- Empresa:\n"
        "- Prazo:\n"
        "- Observações:\n\n"
        "Pendências:\n"
        "- ...\n\n"
        "Próximo passo sugerido:\n..."
    )


def summarize_for_tenant(
    db: Session,
    tenant_id: uuid.UUID,
    source_text: str,
    instruction: str | None = None,
    summary_format: str = "handoff",
    options: dict[str, Any] | None = None,
) -> str:
    """Summarize text using the tenant LLM provider/settings. No RAG is used."""
    fmt = str(summary_format or "handoff").strip().lower()
    if fmt not in SUPPORTED_SUMMARY_FORMATS:
        fmt = "handoff"
    text = str(source_text or "").strip()
    if not text:
        raise AISummaryError("AI_SUMMARY_SOURCE_TEXT_REQUIRED")

    system = (
        "Você é um assistente especializado em resumir conversas de atendimento. "
        "Não invente dados. Quando não houver uma informação, deixe vazio ou indique não informado. "
        "Não use RAG nem base de conhecimento externa; use somente o texto fornecido. "
        f"{_format_instruction(fmt)}"
    )
    if instruction:
        system += f"\nInstrução adicional: {str(instruction)[:2000]}"

    opts = {"temperature": 0.2, "max_tokens": 800, **(options or {})}
    logger.info("[AI SUMMARY] summarize tenant_id=%s format=%s source_length=%s", tenant_id, fmt, len(text))
    try:
        raw = generate_answer_for_tenant(
            db,
            tenant_id,
            [{"role": "system", "content": system}, {"role": "user", "content": text[:20000]}],
            options=opts,
        )
    except (LLMConfigurationError, LLMGenerationError) as exc:
        logger.warning("[AI SUMMARY] provider_failed tenant_id=%s format=%s error=%s", tenant_id, fmt, exc)
        raise AISummaryError("AI_SUMMARY_PROVIDER_FAILED") from exc
    except Exception as exc:
        logger.warning("[AI SUMMARY] failed tenant_id=%s format=%s error=%s", tenant_id, fmt, exc)
        raise AISummaryError("AI_SUMMARY_FAILED") from exc

    cleaned = _clean_text(raw)
    if not cleaned:
        raise AISummaryError("AI_SUMMARY_EMPTY_RESPONSE")
    return cleaned
