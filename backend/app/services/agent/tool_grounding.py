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


_THINK_BLOCK_RE = re.compile(r"[\s\S]*?</think>", re.IGNORECASE)
_THINK_TAG_RE = re.compile(r"</think>", re.IGNORECASE)


def strip_think_tags(content: str) -> str:
    """Remove leaked think blocks and stray tags from model output."""
    text = content or ""
    text = _THINK_BLOCK_RE.sub("", text)
    text = _THINK_TAG_RE.sub("", text)
    return text.strip()

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


_TOOL_FOOTER_RE = re.compile(
    r"\n*\u2014{3,}\s*\n"
    r"(?:\u672c\u56de\u5408\u5b9e\u9645\u5de5\u5177\u8c03\u7528|Tool calls this turn)"
    r"[^\n]*$",
)


def append_tool_call_footer(content: str, tool_names: list[str]) -> str:
    text = (content or "").rstrip()
    return _TOOL_FOOTER_RE.sub("", text).rstrip()

