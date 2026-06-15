from __future__ import annotations

from typing import TYPE_CHECKING

from app.services.agent.integrations import build_integration_system_prompt
from app.services.agent.profile import (
    build_agent_profile_prompt,
    build_agent_resource_snapshot_prompt,
)
from app.services.agent.skills import skill_loader

if TYPE_CHECKING:
    from app.services.agent.agent import Agent


DEFAULT_SYSTEM_PROMPT = "You are a helpful AI assistant."

PERSONA_IDENTITY_LAYER_PROMPT = """Persona Identity Layer:
- Enabled skills with category `persona` define the assistant's conversational identity and self-introduction.
- If a persona skill conflicts with the default TermMan/system identity, follow the persona for ordinary chat and "who are you" questions.
- TermMan is the runtime, tool host, and terminal-control environment. Mention TermMan only when the user asks about platform, tools, backend, terminal management, or implementation.
- Style/tone skills only adjust surface voice. They do not override persona identity."""


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


def _get_agent_skill_prompts(agent: Agent, category: str) -> list[str]:
    prompts: list[str] = []
    for skill in agent.get_skills():
        if skill.category == category and skill.action and skill.action.prompt:
            prompts.append(skill.action.prompt)
    return prompts


def get_system_prompt(agent: Agent | None = None) -> str:
    prompt_parts: list[str] = []
    has_custom_system_prompt = False
    profile_prompt = ""
    resource_snapshot_prompt = ""
    persona_prompts: list[str] = []
    integration_prompt = ""

    if agent is not None:
        system_prompts = _get_agent_skill_prompts(agent, "system")
        if system_prompts:
            prompt_parts.extend(system_prompts)
            has_custom_system_prompt = True

        context = getattr(agent, "_context", None)
        if context is not None:
            profile_prompt = build_agent_profile_prompt(
                getattr(context, "agent_profile", {}) or {}
            )
            resource_snapshot_prompt = build_agent_resource_snapshot_prompt(agent)

        persona_prompts = _get_agent_skill_prompts(agent, "persona")
        integration_prompt = build_integration_system_prompt(agent)

    if not has_custom_system_prompt:
        system_skill = skill_loader.get("system_prompt")
        if system_skill and system_skill.action and system_skill.action.prompt:
            prompt_parts.append(system_skill.action.prompt)
            has_custom_system_prompt = True

    if profile_prompt:
        prompt_parts.append(profile_prompt)
    if resource_snapshot_prompt:
        prompt_parts.append(resource_snapshot_prompt)
    if persona_prompts:
        prompt_parts.append(PERSONA_IDENTITY_LAYER_PROMPT)
        prompt_parts.extend(persona_prompts)
    if integration_prompt:
        prompt_parts.append(integration_prompt)

    unique_parts = _unique_prompt_parts(prompt_parts)
    if not unique_parts:
        return DEFAULT_SYSTEM_PROMPT
    if not has_custom_system_prompt and unique_parts[0] != DEFAULT_SYSTEM_PROMPT:
        unique_parts.insert(0, DEFAULT_SYSTEM_PROMPT)

    return "\n\n".join(unique_parts)
