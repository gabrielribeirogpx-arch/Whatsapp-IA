from __future__ import annotations

import os
from dataclasses import dataclass


def _env_int(name: str, default: int) -> int:
    try:
        return max(0, int(os.getenv(name, str(default))))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class ContextLimits:
    max_history_messages: int = 10
    max_rag_chunks: int = 10
    max_long_memory_items: int = 5
    max_tool_outputs: int = 5
    max_context_chars: int = 16000
    max_context_tokens: int = 4000

    @classmethod
    def defaults(cls) -> "ContextLimits":
        return cls(
            max_history_messages=_env_int("UCE_MAX_HISTORY_MESSAGES", 10),
            max_rag_chunks=_env_int("UCE_MAX_RAG_CHUNKS", 10),
            max_long_memory_items=_env_int("UCE_MAX_LONG_MEMORY_ITEMS", 5),
            max_tool_outputs=_env_int("UCE_MAX_TOOL_OUTPUTS", 5),
            max_context_chars=_env_int("UCE_MAX_CONTEXT_CHARS", 16000),
            max_context_tokens=_env_int("UCE_MAX_CONTEXT_TOKENS", 4000),
        )


def estimate_tokens(value: object) -> int:
    return max(0, len(str(value or "")) // 4)
