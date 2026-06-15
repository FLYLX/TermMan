from __future__ import annotations

from types import SimpleNamespace

from app.services.agent.profile import (
    build_agent_profile_prompt,
    build_agent_resource_snapshot_prompt,
    normalize_agent_profile,
)
from app.services.agent.prompts.system import get_system_prompt
from app.services.agent.skills.definition import ActionConfig, SkillDefinition


def test_normalize_agent_profile_keeps_only_supported_fields() -> None:
    profile = normalize_agent_profile(
        {
            "persona": " quiet operator ",
            "tone": " concise ",
            "language": " zh-CN ",
            "response_rules": [" short replies ", "", 123],
            "avoid": ["pretend tool calls"],
            "extra": "ignored",
        }
    )

    assert profile == {
        "persona": "quiet operator",
        "tone": "concise",
        "language": "zh-CN",
        "response_rules": ["short replies"],
        "avoid": ["pretend tool calls"],
    }


def test_agent_profile_prompt_always_includes_tool_policy() -> None:
    prompt = build_agent_profile_prompt(
        {
            "persona": "若叶睦式安静人格",
            "response_rules": ["短句回复"],
        }
    )

    assert "若叶睦式安静人格" in prompt
    assert "短句回复" in prompt
    assert "Call MCP tools only when" in prompt
    assert "If you did not call a tool in this turn" in prompt
    assert "Persona priority" in prompt


def test_resource_snapshot_includes_skill_revision() -> None:
    context = SimpleNamespace(
        enabled_knowledge_files=["groups/770362397.log"],
        skill_revision=7,
    )
    skills = [SkillDefinition(skill_id="quiet_style", name="Quiet Style")]
    agent = SimpleNamespace(
        _context=context,
        get_skills=lambda: skills,
        get_mcp_servers=lambda: ["robot"],
    )

    prompt = build_agent_resource_snapshot_prompt(agent)

    assert "Skill library revision: 7" in prompt
    assert "quiet_style (Quiet Style)" in prompt
    assert "robot" in prompt
    assert "groups/770362397.log" in prompt


def test_persona_skill_is_system_identity_layer_after_default_identity() -> None:
    system_skill = SkillDefinition(
        skill_id="system_prompt",
        name="System Prompt",
        category="system",
        action=ActionConfig(type="llm", prompt="You are TermMan runtime."),
    )
    persona_skill = SkillDefinition(
        skill_id="kurumi_persona",
        name="Kurumi Persona",
        category="persona",
        action=ActionConfig(
            type="llm",
            prompt="Persona says: answer who-are-you questions as Kurumi.",
        ),
    )
    agent = SimpleNamespace(
        _context=SimpleNamespace(agent_profile={}, enabled_knowledge_files=[], skill_revision=3),
        get_skills=lambda: [system_skill, persona_skill],
        get_mcp_servers=lambda: [],
    )

    prompt = get_system_prompt(agent)

    assert "人格身份层" in prompt
    assert "style/tone skill 只改变表面语气" in prompt
    assert "不要混合身份" in prompt
    assert prompt.index("You are TermMan runtime.") < prompt.index("Persona says")


def test_no_persona_prompt_keeps_identity_blank() -> None:
    system_skill = SkillDefinition(
        skill_id="system_prompt",
        name="System Prompt",
        category="system",
        action=ActionConfig(type="llm", prompt="基础系统提示。"),
    )
    style_skill = SkillDefinition(
        skill_id="kurumi_tone",
        name="Kurumi Tone",
        category="style",
        action=ActionConfig(type="llm", prompt="语气提示。"),
    )
    agent = SimpleNamespace(
        _context=SimpleNamespace(agent_profile={}, enabled_knowledge_files=[], skill_revision=3),
        get_skills=lambda: [system_skill, style_skill],
        get_mcp_servers=lambda: [],
    )

    prompt = get_system_prompt(agent)

    assert "默认身份规则" in prompt
    assert "没有 persona skill 就保持空白身份" in prompt
    assert "不要自称 TermMan" in prompt
    assert "人格身份层" not in prompt
