from __future__ import annotations

from typing import Any

ROBOT_SEND_TOOL_NAME = "mcp_robot_send_message"
ROBOT_QQ_REPLY_EVENT_TYPE = "agent_qq_reply"


def _raw_robot_message_texts(tool_args: dict[str, Any]) -> list[str]:
    messages = tool_args.get("messages")
    if isinstance(messages, list):
        return [str(message or "") for message in messages]

    text = tool_args.get("text")
    if text is None:
        return []
    return [str(text)]


def _compact_visible_text(value: str) -> str:
    try:
        from app.services.agent.integrations.hooks import (
            sanitize_integration_visible_text,
        )

        sanitized = sanitize_integration_visible_text(value)
    except Exception:
        sanitized = str(value or "")
    return " ".join(sanitized.split())


def robot_reply_event_content(
    tool_args: dict[str, Any],
    result_text: str = "",
    *,
    limit: int = 500,
) -> str:
    visible_messages = [
        text
        for raw in _raw_robot_message_texts(tool_args)
        if (text := _compact_visible_text(raw))
    ]
    visible_text = "\n".join(visible_messages).strip()
    if not visible_text:
        visible_text = "(空内容)"
    if len(visible_text) > limit:
        visible_text = visible_text[: limit - 1].rstrip() + "..."

    result_lower = str(result_text or "").casefold()
    duplicate_suppressed = "duplicate qq reply suppressed" in result_lower
    broadcast_with_actual_send = (
        result_lower.startswith("broadcast sent to ")
        and "broadcast sent to 0 qq conversation" not in result_lower
    )
    if duplicate_suppressed and not broadcast_with_actual_send:
        return f"已跳过重复 QQ 回复：{visible_text}"

    return f"已回复 QQ：{visible_text}"
