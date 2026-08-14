from __future__ import annotations

from typing import Any


def build_agent_resource_snapshot_prompt(agent: Any) -> str:
    get_skills = getattr(agent, "get_skills", None)
    get_mcp_servers = getattr(agent, "get_mcp_servers", None)
    context = getattr(agent, "_context", None)

    skills = get_skills() if callable(get_skills) else []
    skill_entries = [
        f"{getattr(skill, 'skill_id', '')} ({getattr(skill, 'name', '')})".strip()
        for skill in skills
        if getattr(skill, "skill_id", "")
        and getattr(skill, "category", "") not in {"persona", "system"}
    ]
    mcp_servers = get_mcp_servers() if callable(get_mcp_servers) else []
    knowledge_files = list(getattr(context, "enabled_knowledge_files", []) or [])
    skill_revision = getattr(context, "skill_revision", 0)

    parts = ["Current Agent Resources:"]
    parts.append(f"- Skill library revision: {skill_revision}")
    parts.append(
        "- Enabled skills: "
        + (", ".join(skill_entries[:16]) if skill_entries else "none")
    )
    parts.append(
        "- Enabled MCP servers: "
        + (", ".join(str(server) for server in mcp_servers[:16]) if mcp_servers else "none")
    )
    parts.append(
        "- Enabled knowledge files: "
        + (", ".join(str(path) for path in knowledge_files[:16]) if knowledge_files else "none")
    )
    parts.append(
        "Use this snapshot as the current truth for available skills, MCP tools, "
        "and knowledge bindings. If the snapshot says none, do not imply such "
        "resources are available."
    )
    return "\n".join(parts)
