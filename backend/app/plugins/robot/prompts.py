from __future__ import annotations

from typing import TYPE_CHECKING

from . import is_robot_plugin_enabled

if TYPE_CHECKING:
    from app.services.agent.agent import Agent


ROBOT_MESSAGING_SKILL_ID = "robot_messaging"
ROBOT_MESSAGING_PROMPT = (
    "Robot Messaging Skill:\n\n"
    "You can send concise user-visible messages through the TermMan "
    "NoneBot/NapCat QQ robot by calling `mcp_robot_send_message`.\n\n"
    "QQ reply reflection:\n"
    "- Before deciding whether to call `mcp_robot_send_message`, silently "
    "re-evaluate whether QQ should receive a reply.\n"
    "- Treat `trigger=mention_bot`, `trigger=reply_to_bot`, direct bot "
    "mentions, replies to the bot, and `trigger=active_chat_window` as "
    "candidate continuations of the bot conversation, not as automatic "
    "permission to send.\n"
    "- If the sender is addressing you, continuing a conversation with you, "
    "challenging or correcting your prior behavior, asking for a useful "
    "response, or explicitly waking the bot with an otherwise empty mention, "
    "call `mcp_robot_send_message`.\n"
    "- If the message is ordinary group chatter with no contextual link to "
    "the bot, directed at someone else, already resolved, or does not need a "
    "bot response, do not call the tool and keep any final response as an "
    "internal TermMan note.\n"
    "- Do not output the reflection itself.\n\n"
    "Target selection:\n"
    "- Incoming QQ messages are shown in context with their source "
    "conversation and sender.\n"
    "- If the system prompt includes `Current robot reply target`, you are "
    "handling an incoming QQ robot conversation. To reply to that current QQ "
    "conversation, call `mcp_robot_send_message` with only `text`; omit "
    "`reply_to`, `conversation`, `broadcast`, `target_type`, and `target_id`.\n"
    "- In an incoming QQ robot conversation, never choose another QQ "
    "conversation. Cross-conversation sends are blocked there to prevent "
    "replying to the wrong group/private chat.\n"
    "- A mention or reply in one group/private chat only wakes that specific "
    "conversation. Recent memory may include other QQ conversations, but do "
    "not send to them unless they are the locked/current target or the user "
    "explicitly selects them from backend chat.\n"
    "- Use `reply_to` only in TermMan backend chat when intentionally "
    "choosing a different QQ conversation visible in context. The backend "
    "resolves that context reference to the actual QQ target.\n"
    "- If you are chatting in the TermMan backend, choose the target from "
    "the QQ context history. If the target is not present or ambiguous, ask "
    "which group/private chat to use.\n"
    "- For severe terminal alerts, if multiple QQ conversations are visible "
    "and they should all receive the same concise alert, call "
    "`mcp_robot_send_message` with `broadcast: true` and `text`.\n\n"
    "Rules:\n"
    "- Your final assistant message is internal to TermMan and will not be "
    "sent to QQ.\n"
    "- Use `target_type` and `target_id` only when the target is outside the "
    "visible QQ context and the user explicitly supplied the group number or "
    "QQ number.\n"
    "- If multiple robots are available and the user specified which robot "
    "to use, pass `robot_id`; otherwise the backend can use the only "
    "accessible enabled robot.\n"
    "- If the target group/private conversation or robot identity is missing "
    "or ambiguous, ask for that value instead of saying there is no robot "
    "context.\n"
    "- Never broadcast or reply to every visible QQ conversation unless the "
    "user explicitly asked for broadcast or a severe alert clearly applies "
    "to all selected targets.\n"
    "- Send only concise, user-visible QQ messages.\n"
    "- Do not invent robot IDs, group IDs, QQ numbers, or target IDs.\n"
    "- Do not send hidden reasoning, tool traces, raw terminal logs, or long "
    "summaries.\n"
    "- If no QQ-side reply is needed, do not call the tool."
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
    return build_robot_messaging_prompt(agent)


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
        "with a concise internal note explaining that no QQ message was sent. "
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
