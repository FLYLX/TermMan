from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.agent.skills import skill_loader

if TYPE_CHECKING:
    from app.services.agent.agent import Agent


DEFAULT_SYSTEM_PROMPT = "You are a helpful AI assistant."
ROBOT_MESSAGING_SKILL_ID = "robot_messaging"
ROBOT_MESSAGING_FALLBACK_PROMPT = (
    "Robot Messaging Skill:\n\n"
    "You can send concise user-visible messages through the TermMan "
    "NoneBot/NapCat QQ robot by calling `mcp_robot_send_message`. "
    "Choose the target from the QQ conversations visible in the current chat "
    "context. If there is more than one possible QQ conversation, pass a short "
    "`reply_to` reference such as the sender name or conversation label, and "
    "the backend resolves it to the actual QQ target. In an incoming QQ robot "
    "conversation, omitting target fields sends to the current QQ conversation; "
    "do not use `reply_to`, `conversation`, `broadcast`, `target_type`, or "
    "`target_id` there because incoming QQ-triggered turns are locked to the "
    "current QQ conversation to prevent replying to the wrong group/private "
    "chat. "
    "being in an awake QQ conversation only means you may evaluate the message, "
    "not that you must reply. Call `mcp_robot_send_message` only when the "
    "sender is addressing you, continuing a conversation with you, asking for "
    "a useful response, or when a severe alert explicitly needs QQ "
    "notification. Do not reply to ordinary group chatter, messages directed "
    "at someone else, or messages that do not need a bot response. Never "
    "broadcast or reply to every visible QQ conversation unless the user "
    "explicitly asked for broadcast or a severe alert clearly applies to all "
    "selected targets. Your final assistant message is internal and will not "
    "be sent to QQ. In "
    "TermMan backend chat, ask which group/private chat to use when the context "
    "does not identify a clear QQ target. "
    "Do not invent robot IDs, group IDs, QQ numbers, or target IDs."
)


def _robot_context_prompt(agent: Agent) -> str:
    context = getattr(agent, "_context", None)
    if context is None or not getattr(context, "robot_id", ""):
        return ""

    prompt_parts: list[str] = []
    robot_skill = skill_loader.get(ROBOT_MESSAGING_SKILL_ID)
    if robot_skill and robot_skill.action and robot_skill.action.prompt:
        prompt_parts.append(robot_skill.action.prompt)
    else:
        prompt_parts.append(ROBOT_MESSAGING_FALLBACK_PROMPT)

    reply_context_summary = str(
        getattr(context, "robot_reply_context_summary", "") or ""
    ).strip()
    if reply_context_summary:
        prompt_parts.append(reply_context_summary)

    return "\n\n".join(prompt_parts)


def _unique_prompt_parts(parts: list[str]) -> list[str]:
    seen: set[str] = set()
    unique_parts: list[str] = []
    for part in parts:
        normalized = part.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        unique_parts.append(normalized)
    return unique_parts


def get_system_prompt(agent: Agent | None = None) -> str:
    prompt_parts: list[str] = []
    has_custom_system_prompt = False
    robot_prompt = ""

    if agent is not None:
        for skill in agent.get_skills():
            if skill.category == "system" and skill.action and skill.action.prompt:
                prompt_parts.append(skill.action.prompt)
                has_custom_system_prompt = True

        robot_prompt = _robot_context_prompt(agent)

    if not has_custom_system_prompt:
        system_skill = skill_loader.get("system_prompt")
        if system_skill and system_skill.action and system_skill.action.prompt:
            prompt_parts.append(system_skill.action.prompt)
            has_custom_system_prompt = True

    if robot_prompt:
        prompt_parts.append(robot_prompt)

    unique_parts = _unique_prompt_parts(prompt_parts)
    if not unique_parts:
        return DEFAULT_SYSTEM_PROMPT
    if not has_custom_system_prompt and unique_parts[0] != DEFAULT_SYSTEM_PROMPT:
        unique_parts.insert(0, DEFAULT_SYSTEM_PROMPT)

    return "\n\n".join(unique_parts)
