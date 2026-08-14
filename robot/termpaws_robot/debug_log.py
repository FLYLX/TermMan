from __future__ import annotations

from typing import Any

LOG_TEXT_PREVIEW_LIMIT = 300


def preview_text(value: Any, limit: int = LOG_TEXT_PREVIEW_LIMIT) -> str:
    text = str(value or "").replace("\r", "\\r").replace("\n", "\\n")
    if len(text) <= limit:
        return text
    return f"{text[:limit]}...<truncated {len(text) - limit} chars>"
