from __future__ import annotations

import logging
import os
import re
import uuid
from typing import Any

import requests
from openai import OpenAI
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.tenant_ai_setting import TenantAISetting
from app.services.ai_model_validation import validate_chat_model
from app.utils.encryption import decrypt_secret

logger = logging.getLogger(__name__)


class LLMConfigurationError(RuntimeError):
    pass


class LLMGenerationError(RuntimeError):
    pass


DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-3.1-flash-lite",
    "anthropic": "claude-3-5-haiku-latest",
    "wazza_default": os.getenv("AI_MODEL", "gemini-3.1-flash-lite"),
}

DEFAULT_TEMPERATURE = 0.2
DEFAULT_MAX_TOKENS = 1200


def _coerce_float(value: Any, *, default: float, field_name: str, source: str) -> float:
    if value is None or value == "":
        logger.info("[AI DEFAULT] field=%s source=%s default=%s reason=missing", field_name, source, default)
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.info("[AI DEFAULT] field=%s source=%s default=%s invalid_value=%r", field_name, source, default, value)
        return default


def _coerce_int(value: Any, *, default: int, field_name: str, source: str) -> int:
    if value is None or value == "":
        logger.info("[AI DEFAULT] field=%s source=%s default=%s reason=missing", field_name, source, default)
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.info("[AI DEFAULT] field=%s source=%s default=%s invalid_value=%r", field_name, source, default, value)
        return default


def _option_or_default(opts: dict[str, Any], key: str, default_factory) -> Any:
    value = opts.get(key)
    return default_factory() if value is None or value == "" else value


def _provider_env_key(provider: str) -> str | None:
    return {
        "openai": "OPENAI_API_KEY",
        "gemini": "GEMINI_API_KEY",
        "anthropic": "ANTHROPIC_API_KEY",
    }.get(provider)


def _sanitize_provider_message(value: Any) -> str:
    message = str(value or "").replace("\n", " ").replace("\r", " ").strip()
    message = re.sub(r"(?i)([?&](?:key|api_key)=)[^&\s]+", r"\1[REDACTED]", message)
    message = re.sub(r"(?i)((?:x-api-key|api-key|authorization)\s*[:=]\s*)(bearer\s+)?\S+", r"\1[REDACTED]", message)
    return message[:500]


def _provider_error_details(exc: Exception) -> tuple[int | None, str | None, str]:
    response = getattr(exc, "response", None)
    status_code = getattr(exc, "status_code", None) or getattr(response, "status_code", None)
    error_code = getattr(exc, "code", None)
    message = getattr(exc, "message", None) or str(exc)

    if response is not None:
        try:
            body = response.json()
        except Exception:
            body = None
        if isinstance(body, dict):
            error = body.get("error")
            if isinstance(error, dict):
                error_code = error_code or error.get("code") or error.get("type") or error.get("status")
                message = error.get("message") or message
            elif isinstance(error, str):
                message = error or message
            else:
                error_code = error_code or body.get("code") or body.get("error_code")
                message = body.get("message") or body.get("detail") or message

    return status_code, str(error_code) if error_code else None, _sanitize_provider_message(message)


def _friendly_provider_error(status_code: int | None, error_code: str | None, message: str) -> str:
    normalized_code = (error_code or "").lower()
    normalized_message = (message or "").lower()
    if (
        status_code == 429
        or "rate_limit" in normalized_code
        or "quota" in normalized_code
        or "resource_exhausted" in normalized_code
        or "rate limit" in normalized_message
        or "quota" in normalized_message
        or "resource exhausted" in normalized_message
    ):
        return "Limite de uso do provedor atingido. Aguarde alguns minutos ou use outro modelo/chave."
    if (
        status_code == 401
        or "invalid_api_key" in normalized_code
        or "api_key_invalid" in normalized_code
        or "authentication" in normalized_code
        or "api key not valid" in normalized_message
        or "invalid api key" in normalized_message
    ):
        return "A chave foi recusada pelo provedor."
    if (
        status_code in {403, 404}
        or "model_not_found" in normalized_code
        or "not_found" in normalized_code
        or "permission" in normalized_message
        or "model" in normalized_message and ("not found" in normalized_message or "not exist" in normalized_message)
    ):
        return "Modelo não encontrado ou sem permissão nesta chave."
    return "Não foi possível validar a conexão com este provedor."


def _wazza_default_provider() -> tuple[str, str | None]:
    provider = os.getenv("AI_PROVIDER", "gemini").strip().lower()
    if provider not in {"openai", "gemini", "anthropic"}:
        provider = "gemini"
    api_key = os.getenv(_provider_env_key(provider) or "") or None
    return provider, api_key


def _wazza_default_chat_model(provider: str) -> str | None:
    return validate_chat_model(os.getenv("AI_MODEL") or DEFAULT_MODELS.get(provider) or DEFAULT_MODELS["wazza_default"])


def _resolve_tenant_config(db: Session | None, tenant_id: uuid.UUID | str | None, options: dict[str, Any] | None = None) -> dict[str, Any]:
    opts = options or {}
    setting = None
    if db is not None and tenant_id is not None:
        setting = db.execute(select(TenantAISetting).where(TenantAISetting.tenant_id == tenant_id)).scalars().first()
    if setting and setting.is_enabled:
        provider = str(setting.provider or "wazza_default").lower()
        api_key = decrypt_secret(setting.encrypted_api_key) if setting.encrypted_api_key else None
        if provider == "wazza_default":
            provider, api_key = _wazza_default_provider()
        elif not api_key:
            raise LLMConfigurationError("IA não configurada para este workspace.")
        return {
            "provider": provider,
            "api_key": api_key,
            "chat_model": validate_chat_model(opts.get("chat_model") or opts.get("model") or setting.chat_model or DEFAULT_MODELS.get(provider)),
            "temperature": _option_or_default(opts, "temperature", lambda: _coerce_float(setting.temperature, default=DEFAULT_TEMPERATURE, field_name="temperature", source="workspace")),
            "max_tokens": _option_or_default(opts, "max_tokens", lambda: _coerce_int(setting.max_tokens, default=DEFAULT_MAX_TOKENS, field_name="max_tokens", source="workspace")),
        }
    provider, api_key = _wazza_default_provider()
    if not api_key:
        raise LLMConfigurationError("IA não configurada para este workspace.")
    return {
        "provider": provider,
        "api_key": api_key,
        "chat_model": validate_chat_model(opts.get("chat_model") or opts.get("model") or os.getenv("AI_MODEL") or DEFAULT_MODELS.get(provider)),
        "temperature": _option_or_default(opts, "temperature", lambda: _coerce_float(os.getenv("AI_TEMPERATURE"), default=DEFAULT_TEMPERATURE, field_name="temperature", source="env")),
        "max_tokens": _option_or_default(opts, "max_tokens", lambda: _coerce_int(os.getenv("AI_MAX_TOKENS"), default=DEFAULT_MAX_TOKENS, field_name="max_tokens", source="env")),
    }


def _messages_to_prompt(messages: list[dict[str, str]]) -> str:
    return "\n\n".join(f"{m.get('role','user').upper()}: {m.get('content','')}" for m in messages)


def _generate_openai(messages: list[dict[str, str]], *, api_key: str, model: str, temperature: float, max_tokens: int) -> str:
    client = OpenAI(api_key=api_key)
    response = client.chat.completions.create(model=model, messages=messages, temperature=temperature, max_tokens=max_tokens)
    return (response.choices[0].message.content or "").strip()


def _generate_gemini(messages: list[dict[str, str]], *, api_key: str, model: str, temperature: float, max_tokens: int) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    payload: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": _messages_to_prompt(messages)}]}],
        "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens},
    }
    response = requests.post(url, params={"key": api_key}, json=payload, timeout=30)
    response.raise_for_status()
    data = response.json()
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    return "".join(part.get("text", "") for part in parts).strip()


def _generate_anthropic(messages: list[dict[str, str]], *, api_key: str, model: str, temperature: float, max_tokens: int) -> str:
    system = "\n".join(m.get("content", "") for m in messages if m.get("role") == "system")
    user_messages = [{"role": "assistant" if m.get("role") == "assistant" else "user", "content": m.get("content", "")} for m in messages if m.get("role") != "system"]
    response = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": api_key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": model, "system": system, "messages": user_messages or [{"role": "user", "content": "Olá"}], "temperature": temperature, "max_tokens": max_tokens},
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()
    return "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text").strip()


def generate_answer(messages: list[dict[str, str]], model: str | None = None, temperature: float | None = None, max_tokens: int | None = None, api_key: str | None = None, provider: str | None = None) -> str:
    resolved_provider = (provider or os.getenv("AI_PROVIDER", "gemini")).strip().lower()
    resolved_key = api_key or os.getenv(_provider_env_key(resolved_provider) or "")
    if not resolved_key:
        raise LLMConfigurationError("IA não configurada para este workspace.")
    resolved_model = validate_chat_model(model) or DEFAULT_MODELS.get(resolved_provider) or "gemini-3.1-flash-lite"
    temp = _coerce_float(temperature if temperature is not None else os.getenv("AI_TEMPERATURE"), default=DEFAULT_TEMPERATURE, field_name="temperature", source="generate_answer")
    limit = _coerce_int(max_tokens if max_tokens is not None else os.getenv("AI_MAX_TOKENS"), default=DEFAULT_MAX_TOKENS, field_name="max_tokens", source="generate_answer")
    try:
        logger.info("[AI PROVIDER CALL] provider=%s model=%s", resolved_provider, resolved_model)
        if resolved_provider == "openai":
            text = _generate_openai(messages, api_key=resolved_key, model=resolved_model, temperature=temp, max_tokens=limit)
        elif resolved_provider == "anthropic":
            text = _generate_anthropic(messages, api_key=resolved_key, model=resolved_model, temperature=temp, max_tokens=limit)
        else:
            text = _generate_gemini(messages, api_key=resolved_key, model=resolved_model, temperature=temp, max_tokens=limit)
        logger.info("[AI PROVIDER RESPONSE] provider=%s model=%s status_code=ok", resolved_provider, resolved_model)
    except LLMConfigurationError:
        raise
    except Exception as exc:
        status_code, error_code, message = _provider_error_details(exc)
        logger.warning(
            "[AI PROVIDER ERROR] provider=%s model=%s status_code=%s error_code=%s message=%s",
            resolved_provider,
            resolved_model,
            status_code,
            error_code,
            message,
        )
        raise LLMGenerationError(_friendly_provider_error(status_code, error_code, message)) from exc
    if not text:
        raise LLMGenerationError("Resposta vazia do provedor de IA")
    return text


def generate_answer_for_tenant(db: Session, tenant_id: uuid.UUID, messages: list[dict[str, str]], options: dict[str, Any] | None = None) -> str:
    config = _resolve_tenant_config(db, tenant_id, options=options)
    return generate_answer(
        messages,
        provider=config["provider"],
        api_key=config["api_key"],
        model=config["chat_model"],
        temperature=_coerce_float(config.get("temperature"), default=DEFAULT_TEMPERATURE, field_name="temperature", source="resolved_config"),
        max_tokens=_coerce_int(config.get("max_tokens"), default=DEFAULT_MAX_TOKENS, field_name="max_tokens", source="resolved_config"),
    )


def test_provider_connection(provider: str, api_key: str, chat_model: str | None = None) -> None:
    provider = provider.strip().lower()
    model = validate_chat_model(chat_model)
    if provider == "wazza_default":
        provider, api_key = _wazza_default_provider()
        model = model or _wazza_default_chat_model(provider)
        if not api_key:
            raise LLMConfigurationError("IA padrão do Wazza não está configurada neste ambiente.")
    elif not model:
        raise LLMConfigurationError("Selecione um modelo de conversação.")
    if not api_key:
        raise LLMConfigurationError("Informe uma API key para testar a conexão.")
    generate_answer(
        [{"role": "user", "content": "Responda apenas OK."}],
        provider=provider,
        api_key=api_key,
        model=model or DEFAULT_MODELS.get(provider),
        temperature=0,
        max_tokens=8,
    )
