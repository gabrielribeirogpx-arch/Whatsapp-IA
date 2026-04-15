import math
import os
import re
from collections import Counter

from openai import OpenAI

DEFAULT_EMBEDDING_MODEL = os.getenv("OPENAI_EMBEDDING_MODEL", "text-embedding-3-small")
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


def generate_embedding(text: str) -> list[float]:
    api_key = os.getenv("OPENAI_API_KEY")
    cleaned = (text or "").strip()
    if not cleaned:
        return []

    if not api_key:
        return _fallback_embedding(cleaned)

    client = OpenAI(api_key=api_key)
    try:
        response = client.embeddings.create(
            model=DEFAULT_EMBEDDING_MODEL,
            input=cleaned,
        )
        return response.data[0].embedding
    except Exception:
        return _fallback_embedding(cleaned)


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
