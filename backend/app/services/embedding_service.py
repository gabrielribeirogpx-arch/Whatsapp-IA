import math
import os
import re
import uuid
from typing import Any

import requests
from sqlalchemy import select
from sqlalchemy.orm import Session
from collections import Counter

from openai import OpenAI

from app.models.tenant_ai_setting import TenantAISetting
from app.services.ai_model_validation import validate_embedding_model
from app.utils.encryption import decrypt_secret

DEFAULT_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
DEFAULT_GEMINI_EMBEDDING_MODEL = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
_TOKEN_RE = re.compile(r"\w+", flags=re.UNICODE)
_FALLBACK_DIMENSION = 256


def _normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(item * item for item in vector))
    if norm == 0:
        return vector
    return [item / norm for item in vector]


def _fallback_embedding(text: str) -> list[float]:
    vector = [0.0] * _FALLBACK_DIMENSION
    tokens = _TOKEN_RE.findall((text or "").lower())
    counts = Counter(tokens)
    for token, count in counts.items():
        index = hash(token) % _FALLBACK_DIMENSION
        vector[index] += float(count)
    return _normalize(vector)



def _embedding_env_key(provider: str) -> str | None:
    return {"openai": "OPENAI_API_KEY", "gemini": "GEMINI_API_KEY"}.get(provider)


def _workspace_embedding_config(db: Session | None, tenant_id: uuid.UUID | None) -> dict[str, Any]:
    setting = None
    if db is not None and tenant_id is not None:
        setting = db.execute(select(TenantAISetting).where(TenantAISetting.tenant_id == tenant_id)).scalars().first()
    provider = (getattr(setting, "embedding_provider", None) or getattr(setting, "provider", None) or os.getenv("EMBEDDING_PROVIDER") or "openai").strip().lower()
    if provider == "wazza_default":
        provider = (os.getenv("AI_PROVIDER") or "openai").strip().lower()
    model = validate_embedding_model(getattr(setting, "embedding_model", None) if setting else None)
    if not model:
        model = DEFAULT_GEMINI_EMBEDDING_MODEL if provider == "gemini" else DEFAULT_EMBEDDING_MODEL
    api_key = decrypt_secret(setting.encrypted_api_key) if setting and setting.encrypted_api_key else None
    api_key = api_key or os.getenv(_embedding_env_key(provider) or "")
    return {"provider": provider, "model": model, "api_key": api_key}


def _generate_provider_embedding(text: str, *, provider: str, model: str, api_key: str | None) -> list[float]:
    if not api_key:
        return _fallback_embedding(text)
    try:
        if provider == "gemini":
            response = requests.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model}:embedContent",
                params={"key": api_key},
                json={"model": f"models/{model}", "content": {"parts": [{"text": text}]}},
                timeout=30,
            )
            response.raise_for_status()
            return response.json().get("embedding", {}).get("values", []) or _fallback_embedding(text)
        if provider == "openai":
            client = OpenAI(api_key=api_key)
            response = client.embeddings.create(model=model, input=text)
            return response.data[0].embedding
    except Exception:
        return _fallback_embedding(text)
    return _fallback_embedding(text)

def generate_embedding(text: str) -> list[float]:
    api_key = os.getenv("OPENAI_API_KEY")
    cleaned = (text or "").strip()
    if not cleaned:
        return []

    if not api_key:
        return _fallback_embedding(cleaned)

    return _generate_provider_embedding(cleaned, provider="openai", model=DEFAULT_EMBEDDING_MODEL, api_key=api_key)


def generate_embedding_for_tenant(db: Session, tenant_id: uuid.UUID, text: str) -> list[float]:
    cleaned = (text or "").strip()
    if not cleaned:
        return []
    config = _workspace_embedding_config(db, tenant_id)
    return _generate_provider_embedding(cleaned, provider=config["provider"], model=config["model"], api_key=config["api_key"])


def cosine_similarity(left: list[float] | None, right: list[float] | None) -> float:
    if not left or not right:
        return 0.0

    shared = min(len(left), len(right))
    if shared == 0:
        return 0.0

    numerator = sum(float(left[index]) * float(right[index]) for index in range(shared))
    left_norm = math.sqrt(sum(float(value) * float(value) for value in left[:shared]))
    right_norm = math.sqrt(sum(float(value) * float(value) for value in right[:shared]))

    if left_norm == 0 or right_norm == 0:
        return 0.0
    return numerator / (left_norm * right_norm)
