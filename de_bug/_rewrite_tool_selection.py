import io
path = r"E:\dev\TermPaws\dev\TermPaws\backend\app\services\agent\tool_selection.py"
content = '''from __future__ import annotations

from typing import Any, Literal

TurnSource = Literal["web", "qq", "terminal"]

LOCAL_PREFIX = "mcp_local_"
ROBOT_PREFIX = "mcp_robot_"


def _tool_name(tool: dict[str, Any]) -> str:
    function = tool.get("function") if isinstance(tool, dict) else None
    if not isinstance(function, dict):
        return ""
    return str(function.get("name") or "").strip()


def select_tools_for_turn(
    tools: list[dict[str, Any]],
    *,
    source: TurnSource,
    query: str = "",
    agent: Any = None,
    reply_ticket_id: str = "",
) -> list[dict[str, Any]]:
    """Return the full tool list for the turn (deduplicated).

    Keyword-based pre-filtering was removed: the agent itself decides which
    tools to use. Pre-filtering by message keywords silently dropped terminal
    tools for legitimate tasks phrased without trigger words.
    """
    del source, query, agent, reply_ticket_id
    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tool in tools:
        name = _tool_name(tool)
        if not name or name in seen:
            continue
        selected.append(tool)
        seen.add(name)
    return selected
'''
with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(content)
print("rewritten")