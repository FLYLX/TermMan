from __future__ import annotations

ROBOT_SEND_TOOL_NAME = "mcp_robot_send_message"


def _normalized_lines(value: str) -> list[str]:
    return [line.strip() for line in str(value or "").splitlines() if line.strip()]


def _is_tool_execution_line(line: str) -> bool:
    return line.startswith("Executing tool:") or line.startswith("执行工具:")


def _is_robot_send_success_line(line: str) -> bool:
    return (
        line.startswith("Message sent to QQ ")
        or line == "Message sent to current robot conversation."
        or line.startswith("Broadcast sent to ")
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
