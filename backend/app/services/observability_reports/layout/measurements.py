"""Deterministic text measurements for the built-in Helvetica compositor."""
from __future__ import annotations

from typing import Any


def wrap_text(value: Any, width: float, size: float = 9) -> list[str]:
    """Approximate Helvetica wrapping without an external font dependency."""
    limit = max(12, int(width / max(size * .52, 1)))
    words, lines, line = str(value or "").split(), [], ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if line and len(candidate) > limit:
            lines.append(line); line = word
        else:
            line = candidate
    return lines + ([line] if line else [""])


def text_lines(value: Any, width: float, size: float = 9) -> int:
    return len(wrap_text(value, width, size))


def text_height(value: Any, width: float, size: float = 9, leading: float | None = None) -> float:
    return text_lines(value, width, size) * (leading or size * 1.42)
