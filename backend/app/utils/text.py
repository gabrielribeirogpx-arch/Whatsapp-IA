from __future__ import annotations

import re
import unicodedata


def normalize_text(text: str) -> str:
    normalized = (text or "").lower().strip()
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = "".join(char for char in normalized if not unicodedata.combining(char))
    normalized = re.sub(r"[^\w\s]", " ", normalized)
    normalized = " ".join(normalized.split())
    return normalized


def tokenize(text: str) -> list[str]:
    normalized = normalize_text(text)
    return [token for token in normalized.split() if len(token) >= 2]
