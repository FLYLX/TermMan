from __future__ import annotations

from typing import TYPE_CHECKING

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


def get_system_prompt(agent: "Agent" | None = None) -> str:
    prompt_parts: list[str] = []

    if agent is not None:
        for skill in agent.get_skills():
            if skill.category == "system" and skill.action and skill.action.prompt:
                prompt_parts.append(skill.action.prompt)

    if not prompt_parts:
        system_skill = skill_loader.get("system_prompt")
        if system_skill and system_skill.action and system_skill.action.prompt:
            prompt_parts.append(system_skill.action.prompt)

    unique_parts = _unique_prompt_parts(prompt_parts)
    if not unique_parts:
        return DEFAULT_SYSTEM_PROMPT

    return "\n\n".join(unique_parts)
