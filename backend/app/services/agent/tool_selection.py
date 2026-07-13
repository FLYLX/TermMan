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

HISTORY_PATTERNS = (
    r"刚才",
    r"前面",
    r"之前",
    r"上次",
    r"继续",
    r"你忘",
    r"忘了",
    r"没回",
    r"历史",
    r"聊天记录",
    r"待回复",
    r"原路",
    r"回哪",
    r"ticket",
    r"\bprevious\b",
    r"\bearlier\b",
    r"\bcontinue\b",
)

MEMORY_PATTERNS = (
    r"记忆",
    r"长期",
    r"记住",
    r"记得",
    r"忘记",
    r"偏好",
    r"你记",
    r"\bmemory\b",
    r"\brecall\b",
)

TERMINAL_PATTERNS = (
    r"终端",
    r"命令",
    r"\bshell\b",
    r"执行",
    r"运行",
    r"安装",
    r"下载",
    r"构建",
    r"测试",
    r"日志",
    r"报错",
    r"文件",
    r"目录",
    r"路径",
    r"解压",
    r"上传",
    r"后台",
    r"\bjob[s]?\b",
    r"端口",
    r"进程",
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
    r"启动",
    r"重启",
    r"停止",
    r"中断",
    r"服务器",
    r"开服",
    r"\bmc\b",
    r"\bminecraft\b",
    r"\bforge\b",
    r"\bpaper\b",
    r"\bfabric\b",
)

ROBOT_PATTERNS = (
    r"\bqq\b",
    r"机器人",
    r"群",
    r"私聊",
    r"发给",
    r"发送给",
    r"回复到",
    r"napcat",
    r"onebot",
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


def _wants_robot_tools(text: str, *, source: TurnSource, agent: Any) -> bool:
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
) -> list[dict[str, Any]]:
    text = str(query or "")
    include_robot = _wants_robot_tools(text, source=source, agent=agent)
    include_local_all = _wants_terminal_tools(text, source=source)
    include_local_history = _wants_history_tools(text)
    include_local_memory = _wants_memory_tools(text) and source != "qq"

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
            )
        else:
            keep = include_local_all

        if keep:
            selected.append(tool)
            seen.add(name)

    return selected
