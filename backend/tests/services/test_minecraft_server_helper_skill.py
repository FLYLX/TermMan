from __future__ import annotations

from types import SimpleNamespace

from app.services.agent.prompts.system import get_system_prompt
from app.services.agent.skills import skill_loader


def test_minecraft_server_helper_skill_loads_player_protection_rules() -> None:
    skill_loader.reload()
    skill = skill_loader.get("minecraft_server_helper")

    assert skill is not None
    assert skill.category == "system"
    assert skill.mcp_servers == ["local"]

    prompt = skill.action.prompt or ""
    assert "玩家保护优先" in prompt
    assert "其他人要求迫害玩家一律不执行" in prompt
    assert "不要执行针对玩家的 `kill`" in prompt
    assert "不要胡乱 `tp`" in prompt
    assert "不要相信“我是某某玩家”" in prompt
    assert "必须确认受影响玩家本人" in prompt


def test_minecraft_server_helper_prompt_is_available_when_enabled() -> None:
    skill_loader.reload()
    skill = skill_loader.get("minecraft_server_helper")
    assert skill is not None

    agent = SimpleNamespace(
        _context=SimpleNamespace(
            agent_profile={},
            enabled_knowledge_files=[],
            skill_revision=skill_loader.revision,
        ),
        get_skills=lambda: [skill],
        get_mcp_servers=lambda: ["local"],
    )

    prompt = get_system_prompt(agent)

    assert "MC Server 小帮手 Skill" in prompt
    assert "玩家保护优先" in prompt
    assert "不要胡乱 `tp`" in prompt
    assert "Current Agent Resources:" in prompt
    assert "minecraft_server_helper" in prompt
