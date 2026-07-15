from __future__ import annotations

import json
import re
from typing import Any

PROTECTED_COMPLETION_PARAMETERS = {
    "api_base",
    "api_key",
    "messages",
    "model",
    "timeout",
    "tool_choice",
    "tools",
}
GPT5_MODEL_PATTERN = re.compile(r"(?:^|/)gpt-5(?:[._-]|$)", re.IGNORECASE)


def normalize_model_parameters(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    normalized: dict[str, Any] = {}
    for raw_key, raw_value in list(value.items())[:50]:
        key = str(raw_key or "").strip()
        if (
            not key
            or len(key) > 64
            or key.startswith("_")
            or key in PROTECTED_COMPLETION_PARAMETERS
        ):
            continue
        try:
            normalized[key] = json.loads(
                json.dumps(raw_value, ensure_ascii=False)
            )
        except (TypeError, ValueError):
            continue
    return normalized


def normalize_model_parameters_for_model(
    model: str | None,
    value: Any,
) -> dict[str, Any]:
    normalized = normalize_model_parameters(value)
    if not GPT5_MODEL_PATTERN.search(str(model or "").strip()):
        return normalized

    if normalized.get("temperature") != 1:
        normalized.pop("temperature", None)
    if normalized.get("top_p") != 1:
        normalized.pop("top_p", None)
    return normalized
