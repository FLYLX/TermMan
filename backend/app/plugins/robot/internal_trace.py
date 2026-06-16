from __future__ import annotations

ROBOT_SEND_TOOL_NAME = "mcp_robot_send_message"
NO_QQ_REPLY_MARKER = "[no_qq_reply]"


def _normalized_lines(value: str) -> list[str]:
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def _is_tool_execution_line(line: str) -> bool:
    return line.startswith("Executing tool:") or line.startswith("执行工具:")


def _contains_robot_send_tool_execution(line: str) -> bool:
    return ROBOT_SEND_TOOL_NAME in line and (
        "Executing tool:" in line or "执行工具:" in line
    )


def _is_robot_send_success_line(line: str) -> bool:
    return (
        line.startswith("Message sent to QQ ")
        or line == "Message sent to current robot conversation."
        or line.startswith("Broadcast sent to ")
    )


def _contains_robot_send_success(line: str) -> bool:
    return (
        "Message sent to QQ " in line
        or "Message sent to current robot conversation." in line
        or "Broadcast sent to " in line
    )


def _is_no_qq_reply_marker_line(line: str) -> bool:
    return line == NO_QQ_REPLY_MARKER or line.endswith(f": {NO_QQ_REPLY_MARKER}")


def _is_internal_send_trace_line(line: str) -> bool:
    return (
        _contains_robot_send_tool_execution(line)
        or _contains_robot_send_success(line)
        or _is_no_qq_reply_marker_line(line)
        or "No QQ message sent:" in line
    )


def is_robot_internal_trace_text(value: str) -> bool:
    lines = _normalized_lines(value)
    if not lines:
        return False

    if _is_robot_send_success_line(lines[0]):
        return True

    if _is_tool_execution_line(lines[0]):
        if ROBOT_SEND_TOOL_NAME not in lines[0]:
            return False
        return all(
            _is_tool_execution_line(line) or _is_robot_send_success_line(line)
            for line in lines
        )

    return False


def sanitize_robot_visible_text(value: str) -> str:
    """Remove robot tool traces from text that may be sent or shown as chat memory."""
    cleaned_lines: list[str] = []
    previous_blank = False
    for raw_line in str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()

        if stripped and _is_internal_send_trace_line(stripped):
            continue

        if NO_QQ_REPLY_MARKER in line:
            line = line.replace(NO_QQ_REPLY_MARKER, "").rstrip()
            stripped = line.strip()
            if not stripped:
                continue

        if not stripped:
            if cleaned_lines and not previous_blank:
                cleaned_lines.append("")
            previous_blank = True
            continue

        cleaned_lines.append(line)
        previous_blank = False

    while cleaned_lines and not cleaned_lines[-1].strip():
        cleaned_lines.pop()

    return "\n".join(cleaned_lines).strip()
