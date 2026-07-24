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

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tool in tools:
        name = _tool_name(tool)
        if not name or name in seen:
            continue

        if name.startswith(ROBOT_PREFIX):
            keep = include_robot
        else:
            # Always include local / other tools and let the model decide
            # whether a tool call is appropriate for the current turn.
            keep = True

        if keep:
            selected.append(tool)
            seen.add(name)

    return selected
