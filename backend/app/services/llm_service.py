from __future__ import annotations

import logging
import os
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
    "gemini": "gemini-1.5-flash",
    "anthropic": "claude-3-5-haiku-latest",
    "wazza_default": os.getenv("AI_MODEL", "gemini-1.5-flash"),
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


def _wazza_default_provider() -> tuple[str, str | None]:
    provider = os.getenv("AI_PROVIDER", "gemini").strip().lower()
    if provider not in {"openai", "gemini", "anthropic"}:
        provider = "gemini"
    api_key = os.getenv(_provider_env_key(provider) or "") or None
    return provider, api_key


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
    resolved_model = validate_chat_model(model) or DEFAULT_MODELS.get(resolved_provider) or "gemini-1.5-flash"
    temp = _coerce_float(temperature if temperature is not None else os.getenv("AI_TEMPERATURE"), default=DEFAULT_TEMPERATURE, field_name="temperature", source="generate_answer")
    limit = _coerce_int(max_tokens if max_tokens is not None else os.getenv("AI_MAX_TOKENS"), default=DEFAULT_MAX_TOKENS, field_name="max_tokens", source="generate_answer")
    try:
        if resolved_provider == "openai":
            text = _generate_openai(messages, api_key=resolved_key, model=resolved_model, temperature=temp, max_tokens=limit)
        elif resolved_provider == "anthropic":
            text = _generate_anthropic(messages, api_key=resolved_key, model=resolved_model, temperature=temp, max_tokens=limit)
        else:
            text = _generate_gemini(messages, api_key=resolved_key, model=resolved_model, temperature=temp, max_tokens=limit)
    except LLMConfigurationError:
        raise
    except Exception as exc:
        raise LLMGenerationError("Falha ao gerar resposta de IA") from exc
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
    if provider == "wazza_default":
        provider, api_key = _wazza_default_provider()
    if not api_key:
        raise LLMConfigurationError("Informe uma API key para testar a conexão.")
    generate_answer(
        [{"role": "user", "content": "Responda apenas OK."}],
        provider=provider,
        api_key=api_key,
        model=validate_chat_model(chat_model) or DEFAULT_MODELS.get(provider),
        temperature=0,
        max_tokens=8,
    )
