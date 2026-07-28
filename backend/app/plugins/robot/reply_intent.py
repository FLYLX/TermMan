from __future__ import annotations

import re

NO_QQ_REPLY_MARKER = "[no_qq_reply]"

_NO_REPLY_EXACTS = {
    "\u65e0\u9700\u56de\u590d",
    "\u4e0d\u9700\u8981\u56de\u590d",
    "\u4e0d\u7528\u56de\u590d",
    "\u4e0d\u56de\u590d",
    "\u6ca1\u5fc5\u8981\u56de\u590d",
    "\u65e0\u9700\u53d1\u9001",
    "\u4e0d\u9700\u8981\u53d1\u9001",
    "\u4e0d\u7528\u53d1\u9001",
    "\u4e0d\u53d1qq",
    "\u4e0d\u7528\u53d1qq",
    "noreply",
    "noqqreply",
    "donotreply",
    "dontreply",
    "donotsend",
    "dontsend",
    "silent",
    "silence",
}

_CHINESE_NO_REPLY_PATTERNS = (
    re.compile(
        r"(?:\u65e0\u9700|\u4e0d\u9700\u8981|\u4e0d\u7528|\u6ca1\u5fc5\u8981)"
        r".{0,8}"
        r"(?:\u56de\u590d|\u56deqq|\u53d1qq|\u53d1\u9001|\u53d1\u6d88\u606f|\u5f80qq\u53d1)"
    ),
    re.compile(
        r"(?:\u4fdd\u6301\u9759\u9ed8|\u9759\u9ed8\u5904\u7406|\u9759\u9ed8\u4f1a\u8bdd|\u5df2\u6b63\u786e\u9759\u9ed8|\u4e0d\u53d1\u8a00|\u65e0\u9700\u8c03\u7528\u7ec8\u7aef)"
    ),
    re.compile(
        r"(?:不是对机器人|不是对bot|不涉及终端操作|群成员之间的|已正确静默处理)"
    ),
)

_ENGLISH_NO_REPLY_PATTERNS = (
    re.compile(
        r"\b(?:no|do not|don't|dont)\s+(?:qq\s+)?(?:reply|response|message|send)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(?:no|do not|don't|dont).{0,24}(?:reply|response|message|send)\b",
        re.IGNORECASE,
    ),
)


def _compact(value: str) -> str:
    compacted = re.sub(
        r"[\s`*_#>\[\]\(\){}\"'\u201c\u201d\u2018\u2019"
        r"\u3002\uff0c\u3001\uff1b;\uff1a:\uff01!\uff1f?\.\-,~\uff5e\u2026]+",
        "",
        value.casefold(),
    )
    return compacted.strip()


def is_no_reply_intent(value: str) -> bool:
    text = (value or "").strip()
    if not text:
        return False

    lowered = text.casefold()
    if NO_QQ_REPLY_MARKER in lowered:
        return True

    compacted = _compact(text)
    if compacted in _NO_REPLY_EXACTS:
        return True

    if len(compacted) <= 200 and any(
        pattern.search(compacted) for pattern in _CHINESE_NO_REPLY_PATTERNS
    ):
        return True

    return len(text) <= 180 and any(
        pattern.search(text) for pattern in _ENGLISH_NO_REPLY_PATTERNS
    )
