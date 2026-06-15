from __future__ import annotations

from typing import TYPE_CHECKING

from . import is_robot_plugin_enabled

if TYPE_CHECKING:
    from app.services.agent.agent import Agent


ROBOT_MESSAGING_SKILL_ID = "robot_messaging"
NO_QQ_REPLY_INSTRUCTION = (
    "- If no QQ-side reply is needed, do not call `mcp_robot_send_message`; "
    "return only `[no_qq_reply]` as the internal final response."
)
ROBOT_MESSAGING_PROMPT = (
    "Robot Messaging Skill:\n\n"
    "Use `mcp_robot_send_message` to send concise QQ-visible messages through "
    "the TermMan NoneBot/NapCat robot. Use "
    "`mcp_robot_read_conversation_memory` only when QQ .log context is needed. "
    "Your final assistant message is internal to TermMan and is not sent to QQ."
)

ROBOT_ACTIVE_CONTEXT_PROMPT = (
    "Active QQ Conversation:\n"
    "- This turn was triggered by one QQ group/private chat only.\n"
    "- Reply to QQ only when the sender is addressing the bot, continuing or "
    "correcting the bot conversation, asking for a useful response, or waking "
    "the bot with an empty mention/reply.\n"
    "- To reply, call `mcp_robot_send_message` with only `text`; omit "
    "`reply_to`, `conversation`, `broadcast`, `target_type`, and `target_id`.\n"
    "- If current .log context is needed, call "
    "`mcp_robot_read_conversation_memory` with no target arguments.\n"
    "- Do not reply to ordinary group chatter or messages directed at someone "
    "else. Do not send hidden reasoning, tool traces, raw logs, or long "
    "summaries.\n"
    f"{NO_QQ_REPLY_INSTRUCTION}"
)

ROBOT_BACKEND_CONTEXT_PROMPT = (
    "QQ Context From History:\n"
    "- Use `reply_to` or `conversation` only when intentionally choosing a QQ "
    "conversation visible in the current TermMan context.\n"
    "- Use `target_type` and `target_id` only when the user explicitly supplied "
    "a QQ group number or QQ number outside visible context.\n"
    "- If the QQ target or robot identity is missing or ambiguous, ask for it.\n"
    "- Broadcast only when the user explicitly asks or a severe alert clearly "
    "applies to every selected QQ conversation."
)

ROBOT_REFLECTION_PROMPT = (
    "QQ Reply Reflection:\n"
    "- Before calling `mcp_robot_send_message`, silently decide whether QQ "
    "should receive a reply.\n"
    "- Mentions, replies to the bot, and active chat window triggers are "
    "candidate continuations, not automatic permission to send.\n"
    f"{NO_QQ_REPLY_INSTRUCTION}"
)


def _robot_context(agent: Agent):
    return getattr(agent, "_context", None)


def _agent_has_robot_messaging_enabled(agent: Agent | None) -> bool:
    if agent is None:
        return False

    get_tools = getattr(agent, "get_tools_for_litellm", None)
    if callable(get_tools):
        try:
            tools = get_tools()
        except Exception:
            tools = []
        for tool in tools or []:
            if not isinstance(tool, dict):
                continue
            if tool.get("function", {}).get("name") == "mcp_robot_send_message":
                return True

    get_servers = getattr(agent, "get_mcp_servers", None)
    if callable(get_servers):
        try:
            if "robot" in set(get_servers() or []):
                return True
        except Exception:
            pass

    get_skills = getattr(agent, "get_skills", None)
    if callable(get_skills):
        try:
            skills = get_skills() or []
        except Exception:
            skills = []
        if any(getattr(skill, "skill_id", "") == ROBOT_MESSAGING_SKILL_ID for skill in skills):
            return True

    return False


def build_robot_messaging_prompt(agent: Agent | None = None) -> str:
    if not is_robot_plugin_enabled():
        return ""

    prompt_parts = [ROBOT_MESSAGING_PROMPT]
    context = _robot_context(agent) if agent is not None else None
    reply_context_summary = str(
        getattr(context, "robot_reply_context_summary", "") or ""
    ).strip()
    if reply_context_summary:
        prompt_parts.append(ROBOT_ACTIVE_CONTEXT_PROMPT)
        prompt_parts.append(reply_context_summary)

    return "\n\n".join(prompt_parts)


def build_robot_context_prompt(agent: Agent) -> str:
    context = _robot_context(agent)
    if context is None or not getattr(context, "robot_id", ""):
        return ""
    return build_robot_messaging_prompt(agent)


def build_robot_history_prompt(agent: Agent, *, has_robot_context: bool) -> str:
    if not has_robot_context:
        return ""
    context = _robot_context(agent)
    if context is not None and getattr(context, "robot_id", ""):
        return ""
    if not _agent_has_robot_messaging_enabled(agent):
        return ""
    return "\n\n".join([ROBOT_MESSAGING_PROMPT, ROBOT_BACKEND_CONTEXT_PROMPT])


def build_robot_delivery_reflection_prompt(final_response: str) -> str:
    if not is_robot_plugin_enabled():
        return ""

    return (
        "Robot message delivery reflection:\n"
        "You produced a final assistant response without calling "
        "`mcp_robot_send_message`:\n"
        f"{final_response.strip()}\n\n"
        "Re-evaluate whether QQ should receive that text. If the current QQ "
        "message is addressed to the bot, continues or corrects a bot "
        "conversation, asks for a useful response, or explicitly wakes the "
        "bot, call `mcp_robot_send_message` now using the locked/current QQ "
        "conversation. If it is ordinary group chatter, directed at someone "
        "else, or no QQ-side response is needed, do not call the tool; respond "
        "only with `[no_qq_reply]` as the internal final response. "
        "Do not output the reflection itself."
    )


def build_robot_messaging_skill_definition():
    if not is_robot_plugin_enabled():
        return None

    from app.services.agent.skills.definition import (
        ActionConfig,
        SafetyConfig,
        SkillDefinition,
        TriggerConfig,
    )

    return SkillDefinition(
        skill_id=ROBOT_MESSAGING_SKILL_ID,
        name="Robot Messaging",
        description=(
            "Allow the agent to send concise proactive messages through the "
            "NoneBot/NapCat QQ robot by MCP."
        ),
        category="integration",
        trigger=TriggerConfig(
            type="manual",
            patterns=[
                "robot",
                "nonebot",
                "napcat",
                "qq",
                "QQ",
                "群",
                "群聊",
                "私信",
                "通知",
                "警告",
                "报警",
                "发消息",
                "发送消息",
            ],
        ),
        action=ActionConfig(type="llm", prompt=ROBOT_MESSAGING_PROMPT),
        safety=SafetyConfig(requires_approval=False, risk_level="medium", max_retries=1, timeout=30),
        mcp_servers=["robot"],
        skill_dir="app/plugins/robot",
    )
