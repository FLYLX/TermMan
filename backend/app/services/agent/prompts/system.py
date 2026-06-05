from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.agent.skills import skill_loader

if TYPE_CHECKING:
    from app.services.agent.agent import Agent


DEFAULT_SYSTEM_PROMPT = "You are a helpful AI assistant."
ROBOT_MESSAGING_SKILL_ID = "robot_messaging"
ROBOT_MESSAGING_FALLBACK_PROMPT = (
    "Robot Messaging Skill:\n\n"
    "You are handling a NoneBot/NapCat QQ robot conversation. "
    "Your final assistant message is internal and will not be sent to QQ. "
    "When you decide the current QQ group or conversation should receive a "
    "message, call `mcp_robot_send_message` with the exact text to send. "
    "The tool always sends to the current robot conversation; do not ask for "
    "or invent QQ group IDs."
)


def _robot_context_prompt(agent: Agent) -> str:
    context = getattr(agent, "_context", None)
    if context is None or not getattr(context, "robot_id", ""):
        return ""

    robot_skill = skill_loader.get(ROBOT_MESSAGING_SKILL_ID)
    if robot_skill and robot_skill.action and robot_skill.action.prompt:
        return robot_skill.action.prompt

    return ROBOT_MESSAGING_FALLBACK_PROMPT


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
