from __future__ import annotations

import ast
import json
import re
from typing import Any

ROBOT_SEND_TOOL_NAME = "mcp_robot_send_message"
_ROBOT_TEXT_ASSIGNMENT_RE = re.compile(
    r'^\s*(?:text|message|content)\s*[:=]\s*(?P<value>[\s\S]+?)\s*$'
)
_JSONISH_KEY_RE = re.compile(
    r'^\s*"?(?:text|messages|target_type|target_id|conversation|reply_to|robot_id|broadcast)"?\s*:'
)


class ToolArgumentParseError(ValueError):
    pass


def parse_tool_arguments(tool_name: str, raw_arguments: str | None) -> dict[str, Any]:
    raw = str(raw_arguments or "").strip()
    if not raw:
        return {}

    direct_robot_args = _parse_robot_text_assignment(tool_name, raw)
    if direct_robot_args is not None:
        return direct_robot_args

    for candidate in _argument_candidates(raw, tool_name):
        try:
            parsed = _parse_candidate(candidate)
        except (json.JSONDecodeError, ValueError, SyntaxError):
            continue

        if isinstance(parsed, dict):
            return _normalize_robot_send_dict(tool_name, parsed)

        robot_args = _coerce_robot_send_value(tool_name, parsed)
        if robot_args is not None:
            return robot_args

    raise ToolArgumentParseError("tool arguments are not valid JSON")


def _argument_candidates(raw: str, tool_name: str) -> list[str]:
    candidates = [raw]
    stripped_fence = _strip_code_fence(raw)
    if stripped_fence != raw:
        candidates.append(stripped_fence)

    for text in list(candidates):
        extracted_object = _extract_balanced_jsonish(text, "{", "}")
        if extracted_object and extracted_object not in candidates:
            candidates.append(extracted_object)
        extracted_array = _extract_balanced_jsonish(text, "[", "]")
        if extracted_array and extracted_array not in candidates:
            candidates.append(extracted_array)

    if tool_name == ROBOT_SEND_TOOL_NAME:
        for text in list(candidates):
            if _JSONISH_KEY_RE.match(text):
                wrapped = "{" + text + "}"
                if wrapped not in candidates:
                    candidates.append(wrapped)

    return candidates


def _strip_code_fence(raw: str) -> str:
    text = raw.strip()
    match = re.fullmatch(r"```(?:json|javascript|js)?\s*([\s\S]*?)\s*```", text)
    if match:
        return match.group(1).strip()
    return text


def _extract_balanced_jsonish(text: str, opener: str, closer: str) -> str | None:
    start = text.find(opener)
    if start < 0:
        return None

    depth = 0
    in_string: str | None = None
    escape = False
    for index in range(start, len(text)):
        char = text[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == in_string:
                in_string = None
            continue

        if char in {'"', "'"}:
            in_string = char
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth == 0:
                return text[start : index + 1].strip()

    return None


def _parse_candidate(candidate: str) -> Any:
    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        return ast.literal_eval(candidate)


def _parse_robot_text_assignment(
    tool_name: str,
    raw: str,
) -> dict[str, Any] | None:
    if tool_name != ROBOT_SEND_TOOL_NAME:
        return None

    match = _ROBOT_TEXT_ASSIGNMENT_RE.match(raw)
    if not match:
        return None

    value = match.group("value").strip()
    if (value.startswith('"') and value.endswith('"')) or (
        value.startswith("'") and value.endswith("'")
    ):
        value = value[1:-1]
    return {"text": value}


def _normalize_robot_send_dict(tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
    if tool_name != ROBOT_SEND_TOOL_NAME:
        return args

    normalized = dict(args)
    if "text" not in normalized:
        for alias in ("message", "content"):
            value = normalized.pop(alias, None)
            if isinstance(value, str) and value.strip():
                normalized["text"] = value
                break
    return normalized


def _coerce_robot_send_value(tool_name: str, value: Any) -> dict[str, Any] | None:
    if tool_name != ROBOT_SEND_TOOL_NAME:
        return None

    if isinstance(value, str):
        text = value.strip()
        if text:
            return {"text": text}

    if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        messages = [item.strip() for item in value if item.strip()]
        if messages:
            return {"messages": messages}

    return None