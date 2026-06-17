from __future__ import annotations

EMBEDDING_MODEL_NAMES = {
    "gemini-embedding-001",
    "gemini-embedding-exp-03-07",
    "text-embedding-004",
    "text-embedding-3-small",
    "text-embedding-3-large",
}
CHAT_MODEL_NAMES = {
    "gemini-3.1-flash-lite",
    "gemini-3-flash",
    "gemini-3.5-flash",
    "gemini-2.5-flash-lite",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "gemini-1.5-flash",
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1-mini",
    "gpt-4.1",
    "claude-3-5-haiku-latest",
    "claude-3-5-sonnet-latest",
    "claude-3-7-sonnet-latest",
    "claude-sonnet",
    "claude-opus",
}

CHAT_MODEL_MARKERS = {
    "flash",
    "pro",
    "sonnet",
    "haiku",
    "opus",
    "gpt-4",
    "gpt-3",
}


def normalize_model(value: str | None) -> str:
    return (value or "").strip().lower()


def is_embedding_model(value: str | None) -> bool:
    model = normalize_model(value)
    return bool(model) and (model in EMBEDDING_MODEL_NAMES or "text-embedding" in model or "embedding" in model)


def is_chat_model(value: str | None) -> bool:
    model = normalize_model(value)
    return bool(model) and (model in CHAT_MODEL_NAMES or any(marker in model for marker in CHAT_MODEL_MARKERS))


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
