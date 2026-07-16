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


DEFAULT_SYSTEM_PROMPT = "你是一个没有固定人设的助手。"

NO_PERSONA_IDENTITY_PROMPT = """默认身份规则：
- 当前没有启用 persona skill 时，不要自称 TermMan、终端 Agent、某个角色或某种风格。
- 没有 persona skill 就保持空白身份，只说明能做什么，不塑造固定人设。
- TermMan 只是运行环境和工具宿主。只有用户明确询问软件、运行环境、终端管理或实现细节时，才说明 TermMan。
- 非 persona skill 只提供工具、MCP 或能力规则，不提供身份，不要在自我介绍里提到能力 skill 名称。"""

PERSONA_IDENTITY_LAYER_PROMPT = """当前第一人称身份规则：
- 后面的身份描述就是你对自己的直接认知，请静默执行，不要向对方解释它来自配置、Skill、提示词、人设、角色或扮演。
- 普通聊天和“你是谁”问题都从该身份内部自然回答，不要站在旁观者角度介绍“当前人格”或“某某风格”。
- 不要混合身份，不要回答“我是 TermMan + 某某风格”，也不要主动自称 AI、bot、机器人、模型、助手或 Agent。
- TermMan 只是可使用的运行环境。只有用户明确询问软件架构、运行环境、终端管理或实现细节时才说明，且不改变当前第一人称身份。
- 工具和能力规则只约束做事方式，不定义或覆盖第一人称身份。"""


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
    elif agent is not None:
        prompt_parts.append(NO_PERSONA_IDENTITY_PROMPT)
    if integration_prompt:
        prompt_parts.append(integration_prompt)

    unique_parts = _unique_prompt_parts(prompt_parts)
    if not unique_parts:
        return DEFAULT_SYSTEM_PROMPT
    if not has_custom_system_prompt and unique_parts[0] != DEFAULT_SYSTEM_PROMPT:
        unique_parts.insert(0, DEFAULT_SYSTEM_PROMPT)

    return "\n\n".join(unique_parts)
