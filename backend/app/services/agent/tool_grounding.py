from __future__ import annotations

import re

_ZH_SUBJECTS = (
    "\u6211",
    "\u8fd9\u8fb9",
    "\u521a\u521a",
    "\u5df2\u7ecf",
    "\u5df2",
)
_ZH_OPTIONAL_PREFIXES = (
    "\u5df2\u7ecf",
    "\u521a\u521a",
)
_ZH_TOOL_VERBS = (
    "\u68c0\u67e5",
    "\u67e5\u770b",
    "\u8bfb\u53d6",
    "\u8fd0\u884c",
    "\u6267\u884c",
    "\u53d1\u9001",
    "\u91cd\u542f",
    "\u542f\u52a8",
    "\u505c\u6b62",
    "\u9a8c\u8bc1",
    "\u641c\u7d22",
    "\u67e5\u8be2",
    "\u8c03\u7528",
    "\u5199\u5165",
    "\u4fdd\u5b58",
    "\u5220\u9664",
    "\u521b\u5efa",
    "\u4fee\u6539",
)
_ZH_COMPLETED_SUFFIXES = (
    "\u4e86",
    "\u8fc7",
    "\u5b8c\u6210",
    "\u6210\u529f",
    "\u597d\u4e86",
)

_CHINESE_TOOL_CLAIM_PATTERNS = (
    re.compile(
        rf"(?:{'|'.join(_ZH_SUBJECTS)})"
        rf"(?:{'|'.join(_ZH_OPTIONAL_PREFIXES)})?"
        rf"(?:{'|'.join(_ZH_TOOL_VERBS)})"
        rf"(?:{'|'.join(_ZH_COMPLETED_SUFFIXES)})?"
    ),
    re.compile(
        rf"(?:{'|'.join(_ZH_TOOL_VERBS)})"
        r"(?:\u5b8c\u6210|\u6210\u529f|\u597d\u4e86|\u8fc7\u4e86)"
    ),
)

_ENGLISH_TOOL_CLAIM_PATTERNS = (
    re.compile(
        r"\b(?:i|i've|i have|we|we've|we have)\s+"
        r"(?:checked|inspected|read|ran|executed|sent|restarted|started|stopped|"
        r"verified|searched|queried|called|wrote|saved|deleted|created|modified)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:checked|inspected|read|ran|executed|sent|restarted|started|stopped|"
        r"verified|searched|queried|called|wrote|saved|deleted|created|modified)\s+"
        r"(?:successfully|already|now)\b",
        re.IGNORECASE,
    ),
)


def has_ungrounded_tool_claim(content: str) -> bool:
    text = (content or "").strip()
    if not text:
        return False
    return any(pattern.search(text) for pattern in _CHINESE_TOOL_CLAIM_PATTERNS) or any(
        pattern.search(text) for pattern in _ENGLISH_TOOL_CLAIM_PATTERNS
    )


def guard_ungrounded_tool_claim(
    content: str,
    *,
    tool_called: bool,
) -> str:
    text = (content or "").strip()
    if not text or tool_called or not has_ungrounded_tool_claim(text):
        return text

    return (
        "\u6211\u6ca1\u6709\u5b9e\u9645\u8c03\u7528 MCP/\u5de5\u5177\uff0c"
        "\u56e0\u6b64\u4e0d\u80fd\u786e\u8ba4\u5916\u90e8\u64cd\u4f5c"
        "\u5df2\u7ecf\u5b8c\u6210\u3002"
        "\u4e0b\u9762\u53ea\u57fa\u4e8e\u5f53\u524d\u4e0a\u4e0b\u6587"
        "\u4f5c\u7b54\uff1a\n"
        f"{text}"
    )
