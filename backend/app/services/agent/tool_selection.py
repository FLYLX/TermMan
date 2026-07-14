from __future__ import annotations

import re
from typing import Any, Literal

TurnSource = Literal["web", "qq", "terminal"]

LOCAL_PREFIX = "mcp_local_"
ROBOT_PREFIX = "mcp_robot_"

LOCAL_HISTORY_TOOLS = {
    "mcp_local_read_chat_history",
    "mcp_local_list_reply_tickets",
}
LOCAL_MEMORY_TOOLS = {
    "mcp_local_save_memory",
    "mcp_local_recall_memory",
    "mcp_local_list_memories",
    "mcp_local_delete_memory",
}
LOCAL_WORKFLOW_TOOLS = {
    "mcp_local_get_task_workflow",
    "mcp_local_update_task_workflow",
    "mcp_local_list_reply_tickets",
    "mcp_local_read_pending_replies",
    "mcp_local_write_pending_reply",
    "mcp_local_delete_pending_reply",
    "mcp_local_send_pending_reply",
}
LOCAL_PENDING_REPLY_TOOLS = {
    "mcp_local_read_pending_replies",
    "mcp_local_write_pending_reply",
    "mcp_local_delete_pending_reply",
    "mcp_local_send_pending_reply",
}
LOCAL_SCHEDULE_TOOLS = {
    "mcp_local_list_scheduled_tasks",
    "mcp_local_write_scheduled_task",
    "mcp_local_delete_scheduled_task",
}

HISTORY_PATTERNS = (
    "\u521a\u624d",
    "\u524d\u9762",
    "\u4e4b\u524d",
    "\u4e0a\u6b21",
    "\u7ee7\u7eed",
    "\u4f60\u8fd8",
    "\u5fd8\u4e86",
    "\u6ca1\u56de",
    "\u5386\u53f2",
    "\u804a\u5929\u8bb0\u5f55",
    "\u5f85\u56de\u590d",
    "\u539f\u8def",
    "\u56de\u54ea",
    "ticket",
    r"\bprevious\b",
    r"\bearlier\b",
    r"\bcontinue\b",
)

MEMORY_PATTERNS = (
    "\u8bb0\u5fc6",
    "\u957f\u671f",
    "\u8bb0\u4f4f",
    "\u8bb0\u5f97",
    "\u5fd8\u8bb0",
    "\u504f\u597d",
    "\u4f60\u8bb0",
    r"\bmemory\b",
    r"\brecall\b",
)

TERMINAL_PATTERNS = (
    "\u7ec8\u7aef",
    "\u547d\u4ee4",
    r"\bshell\b",
    "\u6267\u884c",
    "\u8fd0\u884c",
    "\u5b89\u88c5",
    "\u4e0b\u8f7d",
    "\u6784\u5efa",
    "\u6d4b\u8bd5",
    "\u65e5\u5fd7",
    "\u62a5\u9519",
    "\u6587\u4ef6",
    "\u76ee\u5f55",
    "\u8def\u5f84",
    "\u89e3\u538b",
    "\u4e0a\u4f20",
    "\u540e\u53f0",
    r"\bjob[s]?\b",
    "\u7aef\u53e3",
    "\u8fdb\u7a0b",
    r"\bps\b",
    r"\bls\b",
    r"\bcat\b",
    r"\bgrep\b",
    r"\bfind\b",
    r"\bdocker\b",
    r"\bjava\b",
    r"\bjvm\b",
    r"\bpython\b",
    r"\bpip\b",
    r"\bnpm\b",
    r"\bbun\b",
    r"\bapt\b",
    r"\bcurl\b",
    r"\bwget\b",
    r"\bgit\b",
    "\u542f\u52a8",
    "\u91cd\u542f",
    "\u505c\u6b62",
    "\u4e2d\u65ad",
    "\u670d\u52a1\u5668",
    "\u5f00\u670d",
    "\u95ee\u95ee",
    "\u95ee\u4e00\u4e0b",
    "\u5e2e\u6211\u95ee",
    "\u5e2e\u5fd9\u95ee",
    "\u8f6c\u95ee",
    r"\bmc\b",
    r"\bminecraft\b",
    r"\bforge\b",
    r"\bpaper\b",
    r"\bfabric\b",
)

PENDING_REPLY_PATTERNS = (
    "\u5f85\u56de\u590d",
    "\u56de\u590d\u961f\u5217",
    "\u539f\u8def\u56de\u590d",
    "\u56de\u62a5",
    "\u6c47\u62a5",
    "\u95ee\u95ee",
    "\u5e2e\u6211\u95ee",
    "\u8f6c\u95ee",
    "pending repl",
)

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

SCHEDULE_PATTERNS = (
    "\u5b9a\u65f6\u4efb\u52a1",
    "\u8ba1\u5212\u4efb\u52a1",
    "\u5b9a\u65f6\u6267\u884c",
    "\u6bcf\u5929.*\u6267\u884c",
    "\u6bcf\u9694.*\u6267\u884c",
    "scheduled task",
    r"\bschedule\b",
    r"\bcron\b",
)


def _tool_name(tool: dict[str, Any]) -> str:
    function = tool.get("function") if isinstance(tool, dict) else None
    if not isinstance(function, dict):
        return ""
    return str(function.get("name") or "").strip()


def _matches_any(text: str, patterns: tuple[str, ...]) -> bool:
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def _wants_terminal_tools(text: str, *, source: TurnSource) -> bool:
    if source == "terminal":
        return True
    return _matches_any(text, TERMINAL_PATTERNS)


def _wants_history_tools(text: str) -> bool:
    return _matches_any(text, HISTORY_PATTERNS)


def _wants_memory_tools(text: str) -> bool:
    return _matches_any(text, MEMORY_PATTERNS)


def _wants_schedule_tools(text: str) -> bool:
    return _matches_any(text, SCHEDULE_PATTERNS)


def _wants_pending_reply_tools(text: str) -> bool:
    return _matches_any(text, PENDING_REPLY_PATTERNS)


def _wants_robot_tools(text: str, *, source: TurnSource, agent: Any) -> bool:
    del agent
    if source == "qq":
        return True
    if source == "terminal":
        return False
    return _matches_any(text, ROBOT_PATTERNS)


def _has_active_task_workflow(agent: Any) -> bool:
    context = getattr(agent, "_context", None)
    ticket_id = str(getattr(context, "reply_ticket_id", "") or "").strip()
    if not ticket_id:
        return False
    try:
        from app.services.agent.task_workflow import task_workflow_manager

        workflow = task_workflow_manager.get_by_ticket(ticket_id)
        return bool(workflow and workflow.status not in {"completed", "cancelled"})
    except Exception:
        return False


def select_tools_for_turn(
    tools: list[dict[str, Any]],
    *,
    source: TurnSource,
    query: str = "",
    agent: Any = None,
) -> list[dict[str, Any]]:
    text = str(query or "")
    include_robot = _wants_robot_tools(text, source=source, agent=agent)
    include_local_schedule = _wants_schedule_tools(text)
    is_scheduled_execution = text.lstrip().lower().startswith(
        ("scheduled task", "[scheduled task]")
    )
    include_local_all = _wants_terminal_tools(text, source=source) and (
        not include_local_schedule or is_scheduled_execution
    )
    include_local_history = _wants_history_tools(text)
    include_local_memory = _wants_memory_tools(text) and source != "qq"
    include_local_workflow = _has_active_task_workflow(agent)
    include_local_pending_replies = _wants_pending_reply_tools(text)

    selected: list[dict[str, Any]] = []
    seen: set[str] = set()
    for tool in tools:
        name = _tool_name(tool)
        if not name or name in seen:
            continue

        keep = False
        if name.startswith(ROBOT_PREFIX):
            keep = include_robot
        elif name.startswith(LOCAL_PREFIX):
            keep = (
                include_local_all
                or (include_local_history and name in LOCAL_HISTORY_TOOLS)
                or (include_local_memory and name in LOCAL_MEMORY_TOOLS)
                or (include_local_workflow and name in LOCAL_WORKFLOW_TOOLS)
                or (
                    include_local_pending_replies
                    and name in LOCAL_PENDING_REPLY_TOOLS
                )
                or (include_local_schedule and name in LOCAL_SCHEDULE_TOOLS)
            )
        else:
            keep = include_local_all

        if keep:
            selected.append(tool)
            seen.add(name)

    return selected
