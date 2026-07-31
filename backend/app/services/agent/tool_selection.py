from __future__ import annotations

import re
from typing import Any, Literal

TurnSource = Literal["web", "qq", "terminal"]

LOCAL_PREFIX = "mcp_local_"
ROBOT_PREFIX = "mcp_robot_"

ROBOT_PATTERNS = (
    r"\bqq\b",
    "\u673a\u5668\u4eba",
    "\u7fa4",
    "\u79c1\u804a",
    "\u53d1\u7ed9",
    "\u53d1\u9001\u7ed9",
    "\u56de\u590d\u5230",
    "napcat",
    "onebot",
)

TERMINAL_TOOL_PATTERNS = (
    "\u7ec8\u7aef", "\u547d\u4ee4", "\u65e5\u5fd7", "shell", "command",
    "\u5b89\u88c5", "\u4e0b\u8f7d", "\u6784\u5efa", "java", "minecraft",
    "\u670d\u52a1\u5668", "\u542f\u52a8", "\u505c\u6b62", "\u8fd0\u884c",
    "\u6267\u884c", "\u67e5\u770b", "\u68c0\u67e5", "terminal", "install",
    "run", "build", "start", "stop", "status", "job", "\u811a\u672c",
    "\u8fdb\u7a0b", "\u914d\u7f6e", "\u7f16\u8bd1", "\u5378\u8f7d", "\u5347\u7ea7",
)

TERMINAL_ONLY_TOOLS = {
    "mcp_local_execute_command",
    "mcp_local_run_job",
    "mcp_local_get_terminal_status",
    "mcp_local_read_terminal_log",
    "mcp_local_interrupt_command",
    "mcp_local_add_terminal_input_filter_rule",
    "mcp_local_list_terminal_input_filter_rules",
    "mcp_local_list_terminal_filter_rules",
    "mcp_local_delete_terminal_input_filter_rule",
    "mcp_local_clear_terminal_input_filter_rules",
    "mcp_local_list_jobs",
    "mcp_local_cancel_job",
}


def _tool_name(tool: dict[str, Any]) -> str:
    function = tool.get("function") if isinstance(tool, dict) else None
    if not isinstance(function, dict):
        return ""
    return str(function.get("name") or "").strip()


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _wants_robot_tools(text: str, *, source: TurnSource, agent: Any) -> bool:
    del agent
    if source == "qq":
        return True
    if source == "terminal":
        return False
    return _matches_any(text, ROBOT_PATTERNS)


def _wants_terminal_tools(text: str, source: TurnSource) -> bool:
    if source == "terminal":
        return True
    return _matches_any(text, TERMINAL_TOOL_PATTERNS)


def select_tools_for_turn(
    tools: list[dict[str, Any]],
    *,
    source: TurnSource,
    query: str = "",
    agent: Any = None,
    reply_ticket_id: str = "",
) -> list[dict[str, Any]]:
    text = str(query or "")
    include_robot = _wants_robot_tools(text, source=source, agent=agent)
    include_terminal = _wants_terminal_tools(text, source=source)

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tool in tools:
        name = _tool_name(tool)
        if not name or name in seen:
            continue

        if name.startswith(ROBOT_PREFIX):
            keep = include_robot
        elif name in TERMINAL_ONLY_TOOLS:
            keep = include_terminal
        else:
            keep = True

        if keep:
            selected.append(tool)
            seen.add(name)

    return selected
