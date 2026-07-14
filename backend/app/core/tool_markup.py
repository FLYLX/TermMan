from __future__ import annotations

import html
import json
import re
from typing import Any

_DSML_MARKER = r"(?:\|\|DSML\|\||｜｜DSML｜｜)"
_DSML_INVOKE_RE = re.compile(
    rf"<{_DSML_MARKER}invoke\b(?P<attrs>[^>]*)>"
    rf"(?P<body>.*?)"
    rf"</{_DSML_MARKER}invoke\s*>",
    re.IGNORECASE | re.DOTALL,
)
_DSML_PARAMETER_RE = re.compile(
    rf"<{_DSML_MARKER}parameter\b(?P<attrs>[^>]*)>"
    rf"(?P<body>.*?)"
    rf"</{_DSML_MARKER}parameter\s*>",
    re.IGNORECASE | re.DOTALL,
)
_DSML_COMPLETE_BLOCK_RE = re.compile(
    rf"<{_DSML_MARKER}(?:tool_calls|invoke)\b[^>]*>.*?"
    rf"</{_DSML_MARKER}(?:tool_calls|invoke)\s*>",
    re.IGNORECASE | re.DOTALL,
)
_DSML_PARAMETER_BLOCK_RE = re.compile(
    rf"<{_DSML_MARKER}parameter\b[^>]*>.*?"
    rf"</{_DSML_MARKER}parameter\s*>",
    re.IGNORECASE | re.DOTALL,
)
_DSML_OPEN_CONTROL_RE = re.compile(
    rf"<{_DSML_MARKER}(?:tool_calls|invoke)\b[^>]*>",
    re.IGNORECASE,
)
_DSML_TAG_RE = re.compile(
    rf"</?{_DSML_MARKER}(?:tool_calls|invoke|parameter)\b[^>]*>",
    re.IGNORECASE,
)
_ATTRIBUTE_RE = re.compile(
    r"(?P<name>[A-Za-z_][\w:.-]*)\s*=\s*(?P<quote>['\"])(?P<value>.*?)(?P=quote)",
    re.DOTALL,
)


def contains_dsml_tool_markup(value: Any) -> bool:
    return bool(_DSML_TAG_RE.search(str(value or "")))


def strip_dsml_tool_markup(value: Any) -> str:
    """Remove complete or truncated DSML tool-call markup from visible text."""
    text = str(value or "")
    if not contains_dsml_tool_markup(text):
        return text

    cleaned = _DSML_COMPLETE_BLOCK_RE.sub("", text)
    cleaned = _DSML_PARAMETER_BLOCK_RE.sub("", cleaned)
    truncated_open = _DSML_OPEN_CONTROL_RE.search(cleaned)
    if truncated_open:
        cleaned = cleaned[: truncated_open.start()]
    cleaned = _DSML_TAG_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _attributes(value: str) -> dict[str, str]:
    return {
        match.group("name").lower(): html.unescape(match.group("value"))
        for match in _ATTRIBUTE_RE.finditer(value)
    }


def _parameter_value(raw_value: str, attributes: dict[str, str]) -> Any:
    value = html.unescape(strip_dsml_tool_markup(raw_value)).strip()
    if attributes.get("boolean", "").lower() == "true":
        return value.lower() in {"1", "true", "yes", "on"}
    if attributes.get("number", "").lower() == "true":
        try:
            return int(value)
        except ValueError:
            try:
                return float(value)
            except ValueError:
                return value
    if attributes.get("json", "").lower() == "true":
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def extract_dsml_tool_calls(
    value: Any,
    *,
    allowed_tool_names: set[str],
) -> tuple[str, list[dict[str, Any]]]:
    """Convert DSML fallback markup into regular tool calls.

    Some OpenAI-compatible providers stream their fallback tool protocol inside
    ``content`` instead of ``delta.tool_calls``. Only tools offered in the
    current request are accepted; all DSML markup is removed from visible text.
    """
    text = str(value or "")
    if not contains_dsml_tool_markup(text):
        return text, []

    tool_calls: list[dict[str, Any]] = []
    for invoke in _DSML_INVOKE_RE.finditer(text):
        invoke_attributes = _attributes(invoke.group("attrs"))
        tool_name = invoke_attributes.get("name", "").strip()
        if not tool_name or tool_name not in allowed_tool_names:
            continue

        arguments: dict[str, Any] = {}
        for parameter in _DSML_PARAMETER_RE.finditer(invoke.group("body")):
            parameter_attributes = _attributes(parameter.group("attrs"))
            parameter_name = parameter_attributes.get("name", "").strip()
            if not parameter_name:
                continue
            arguments[parameter_name] = _parameter_value(
                parameter.group("body"),
                parameter_attributes,
            )

        tool_calls.append(
            {
                "id": f"call_dsml_{len(tool_calls)}",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
            }
        )

    return strip_dsml_tool_markup(text), tool_calls
