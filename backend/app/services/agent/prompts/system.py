from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.agent.integrations import build_integration_system_prompt
from app.services.agent.skills import skill_loader

if TYPE_CHECKING:
    from app.services.agent.agent import Agent


DEFAULT_SYSTEM_PROMPT = "You are a helpful AI assistant."


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
    integration_prompt = ""

    if agent is not None:
        for skill in agent.get_skills():
            if skill.category == "system" and skill.action and skill.action.prompt:
                prompt_parts.append(skill.action.prompt)
                has_custom_system_prompt = True

        integration_prompt = build_integration_system_prompt(agent)

    if not has_custom_system_prompt:
        system_skill = skill_loader.get("system_prompt")
        if system_skill and system_skill.action and system_skill.action.prompt:
            prompt_parts.append(system_skill.action.prompt)
            has_custom_system_prompt = True

    if integration_prompt:
        prompt_parts.append(integration_prompt)

    unique_parts = _unique_prompt_parts(prompt_parts)
    if not unique_parts:
        return DEFAULT_SYSTEM_PROMPT
    if not has_custom_system_prompt and unique_parts[0] != DEFAULT_SYSTEM_PROMPT:
        unique_parts.insert(0, DEFAULT_SYSTEM_PROMPT)

    return "\n\n".join(unique_parts)
