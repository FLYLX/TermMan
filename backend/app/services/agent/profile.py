from __future__ import annotations

from typing import Any

DEFAULT_TOOL_POLICY = (
    "Call MCP tools only when the current task needs external state, terminal "
    "state, files, robot delivery, or knowledge not already present in the "
    "prompt. Do not call tools for ordinary chat, style-only replies, or when "
    "the answer is already known from the supplied context."
)

TOOL_GROUNDING_RULES = (
    "Tool grounding rules:\n"
    "- If you did not call a tool in this turn, do not say that you checked, "
    "ran, sent, read, restarted, verified, or inspected anything.\n"
    "- If a tool call fails, say it failed and use the actual error. Do not "
    "invent a successful result.\n"
    "- Base claims about terminal state, files, robot delivery, MCP, and "
    "knowledge search on the latest tool result or prompt context only.\n"
    "- Prefer one purposeful tool call over repeated probing. Stop once the "
    "tool result is enough to answer."
)


def _clean_text(value: Any, *, max_length: int = 1200) -> str:
    if not isinstance(value, str):
        return ""
    return value.strip()[:max_length]


def _clean_text_list(value: Any, *, max_items: int = 8, max_length: int = 280) -> list[str]:
    if not isinstance(value, list):
        return []
    cleaned: list[str] = []
    for item in value:
        text = _clean_text(item, max_length=max_length)
        if text:
            cleaned.append(text)
        if len(cleaned) >= max_items:
            break
    return cleaned


def normalize_agent_profile(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}

    profile: dict[str, Any] = {}
    for key in ("persona", "tone", "language", "verbosity", "tool_policy"):
        text = _clean_text(value.get(key))
        if text:
            profile[key] = text

    response_rules = _clean_text_list(value.get("response_rules"))
    if response_rules:
        profile["response_rules"] = response_rules

    avoid = _clean_text_list(value.get("avoid"))
    if avoid:
        profile["avoid"] = avoid

    return profile


def build_agent_profile_prompt(profile: dict[str, Any] | None) -> str:
    normalized = normalize_agent_profile(profile)
    parts = ["Agent Profile:"]

    persona = _clean_text(normalized.get("persona"))
    if persona:
        parts.append(f"- Persona: {persona}")
        parts.append(
            "- Persona priority: Use this persona for self-introduction and "
            "ordinary chat identity. Mention TermMan only for runtime, tool, "
            "backend, or terminal-management questions."
        )

    tone = _clean_text(normalized.get("tone"))
    if tone:
        parts.append(f"- Tone: {tone}")

    language = _clean_text(normalized.get("language"))
    if language:
        parts.append(f"- Language preference: {language}")

    verbosity = _clean_text(normalized.get("verbosity"))
    if verbosity:
        parts.append(f"- Verbosity: {verbosity}")

    response_rules = _clean_text_list(normalized.get("response_rules"))
    if response_rules:
        parts.append("- Response rules:")
        parts.extend(f"  - {rule}" for rule in response_rules)

    avoid = _clean_text_list(normalized.get("avoid"))
    if avoid:
        parts.append("- Avoid:")
        parts.extend(f"  - {rule}" for rule in avoid)

    tool_policy = _clean_text(normalized.get("tool_policy")) or DEFAULT_TOOL_POLICY
    parts.append(f"- Tool policy: {tool_policy}")
    parts.append(TOOL_GROUNDING_RULES)

    return "\n".join(parts)


def build_agent_resource_snapshot_prompt(agent: Any) -> str:
    get_skills = getattr(agent, "get_skills", None)
    get_mcp_servers = getattr(agent, "get_mcp_servers", None)
    context = getattr(agent, "_context", None)

    skills = get_skills() if callable(get_skills) else []
    skill_entries = [
        f"{getattr(skill, 'skill_id', '')} ({getattr(skill, 'name', '')})".strip()
        for skill in skills
        if getattr(skill, "skill_id", "")
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
