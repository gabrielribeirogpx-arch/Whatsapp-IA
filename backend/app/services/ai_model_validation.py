from __future__ import annotations

EMBEDDING_MODEL_NAMES = {
    "gemini-embedding-001",
    "text-embedding-3-small",
    "text-embedding-3-large",
}
CHAT_MODEL_NAMES = {
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-1.5-flash",
    "gpt-4o",
    "gpt-4o-mini",
    "claude-sonnet",
    "claude-opus",
    "claude-3-5-haiku-latest",
}


def normalize_model(value: str | None) -> str:
    return (value or "").strip().lower()


def is_embedding_model(value: str | None) -> bool:
    model = normalize_model(value)
    return bool(model) and (model in EMBEDDING_MODEL_NAMES or "text-embedding" in model or "embedding" in model)


def is_chat_model(value: str | None) -> bool:
    model = normalize_model(value)
    return bool(model) and (model in CHAT_MODEL_NAMES or model.startswith("gpt-4") or model.startswith("claude") or model.startswith("gemini-1.5") or model.startswith("gemini-2.5"))


def validate_chat_model(value: str | None) -> str | None:
    model = (value or "").strip()
    if not model:
        return None
    if is_embedding_model(model):
        raise ValueError("Este é um modelo de embeddings. Selecione um modelo de conversação.")
    return model


def validate_embedding_model(value: str | None) -> str | None:
    model = (value or "").strip()
    if not model:
        return None
    if is_chat_model(model):
        raise ValueError("Este é um modelo de conversação. Selecione um modelo de embeddings.")
    return model
