"""Grounding helpers for final agent replies.

The agent's reply text is never censored and never pattern-matched: it is
delivered as-is. What the system adds is ground truth from the turn's actual
tool-call record — a compact footer shown next to the reply, so "claimed"
and "actually done" are visible side by side.

The only content still replaced outright is a fabricated tool trace (the
model printing fake ``Executing tool: mcp_...`` / ``执行工具: mcp_...``
lines): that is the model impersonating system output, not a figure of
speech, and detecting it carries essentially no false positives.
"""

from __future__ import annotations

import re

_FABRICATED_TOOL_TRACE_RE = re.compile(
    r"(?:Executing tool:|执行工具:)\s*mcp_[a-z0-9_]+",
    re.IGNORECASE,
)

_FABRICATED_TRACE_FALLBACK_ZH = (
    "我没有实际调用工具，因此这次外部操作没有执行。"
)
_FABRICATED_TRACE_FALLBACK_EN = (
    "I did not call a tool, so the external operation was not performed."
)

_CJK_RE = re.compile(r"[一-鿿]")


def has_fabricated_tool_trace(content: str) -> bool:
    text = (content or "").strip()
    return bool(text) and bool(_FABRICATED_TOOL_TRACE_RE.search(text))


def guard_fabricated_tool_trace(content: str) -> str:
    """Replace a fabricated tool trace with an honest fallback.

    Normal reply text — including text that merely *reads* like an action
    claim — is returned unchanged.
    """
    text = (content or "").strip()
    if not text or not has_fabricated_tool_trace(text):
        return text
    if _CJK_RE.search(text):
        return _FABRICATED_TRACE_FALLBACK_ZH
    return _FABRICATED_TRACE_FALLBACK_EN


def _compress_tool_names(names: list[str]) -> list[str]:
    """Collapse consecutive duplicate tool names into ``name ×k``."""
    compressed: list[str] = []
    last = ""
    count = 0
    for name in names:
        if name == last:
            count += 1
            continue
        if last:
            compressed.append(last if count == 1 else f"{last} ×{count}")
        last = name
        count = 1
    if last:
        compressed.append(last if count == 1 else f"{last} ×{count}")
    return compressed


def append_tool_call_footer(content: str, tool_names: list[str]) -> str:
    """Append an authoritative execution summary to a final reply.

    ``tool_names`` is the ordered list of tool calls that actually executed
    during the turn. The footer is built from that structured record only —
    no inspection of the reply text — so it cannot be fooled by phrasing and
    cannot hide useful content.
    """
    text = (content or "").rstrip()
    if not text:
        return text
    names = [
        str(name or "").strip()
        for name in (tool_names or [])
        if str(name or "").strip()
    ]
    if names:
        summary = ", ".join(_compress_tool_names(names))
        if _CJK_RE.search(text):
            line = f"本回合实际工具调用:{len(names)} 次 [{summary}]"
        else:
            line = f"Tool calls this turn: {len(names)} [{summary}]"
    else:
        if _CJK_RE.search(text):
            line = "本回合实际工具调用:0 次"
        else:
            line = "Tool calls this turn: 0"
    return f"{text}\n\n———\n{line}"
