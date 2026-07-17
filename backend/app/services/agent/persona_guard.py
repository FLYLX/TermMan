from __future__ import annotations

import hashlib
import re
from typing import Any

YUI_PERSONA_SKILL_IDS = {"hirasawa_yui_persona", "hirasawa_yui_tone"}
CURRENT_QQ_MESSAGE_MARKER = "[Current QQ message]"
CQ_CODE_RE = re.compile(r"\[CQ:[^\]]+\]")
YUI_IDENTITY_QUERY_RE = re.compile(
    r"^(?:(?:说起来|话说|那个|欸|诶|所以)\s*)?"
    r"(?:你(?:到底|究竟)?是谁|你叫(?:什么|啥)(?:名字)?|"
    r"(?:介绍|说说)(?:一下)?(?:你自己|自己)|"
    r"你是(?:ai|人工智能|机器人|bot|模型|助手)(?:吗|嘛)?)"
    r"[啊呀呢嘛吧哦？?！!。,.，\s]*$",
    re.IGNORECASE,
)
YUI_IDENTITY_REPLIES = (
    "我是唯呀，平泽唯。怎么突然问这个？",
    "欸，我是平泽唯呀。你怎么突然考我？",
    "平泽唯呀。怎么，突然不认识我啦？",
)


def _current_message_text(message: str) -> str:
    text = str(message or "").strip()
    if CURRENT_QQ_MESSAGE_MARKER in text:
        text = text.rsplit(CURRENT_QQ_MESSAGE_MARKER, 1)[-1].strip()
    return CQ_CODE_RE.sub("", text).strip()


def _enabled_skill_ids(agent: Any) -> set[str]:
    get_skills = getattr(agent, "get_skills", None)
    if not callable(get_skills):
        return set()
    try:
        skills = get_skills() or []
    except Exception:
        return set()
    return {
        str(getattr(skill, "skill_id", "") or "").strip()
        for skill in skills
        if str(getattr(skill, "skill_id", "") or "").strip()
    }


def persona_identity_reply(agent: Any, message: str) -> str | None:
    if not YUI_PERSONA_SKILL_IDS.intersection(_enabled_skill_ids(agent)):
        return None
    current_message = _current_message_text(message)
    if not YUI_IDENTITY_QUERY_RE.fullmatch(current_message):
        return None
    digest = hashlib.sha1(current_message.encode("utf-8")).digest()
    return YUI_IDENTITY_REPLIES[digest[0] % len(YUI_IDENTITY_REPLIES)]


def enforce_persona_identity_response(agent: Any, message: str, content: str) -> str:
    return persona_identity_reply(agent, message) or str(content or "")


def enforce_persona_identity_robot_tool_args(
    agent: Any,
    message: str,
    tool_args: dict[str, Any],
) -> dict[str, Any]:
    reply = persona_identity_reply(agent, message)
    if not reply:
        return tool_args
    normalized = dict(tool_args)
    normalized.pop("messages", None)
    normalized["text"] = reply
    return normalized
