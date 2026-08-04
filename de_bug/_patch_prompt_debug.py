import pathlib

# system.py: log part sizes
sp = pathlib.Path("backend/app/services/agent/prompts/system.py")
src = sp.read_text(encoding="utf-8")
assert "PROMPT_DEBUG" not in src
old = '''    unique_parts = _unique_prompt_parts(prompt_parts)
    if not unique_parts:
        return DEFAULT_SYSTEM_PROMPT
    if not has_custom_system_prompt and unique_parts[0] != DEFAULT_SYSTEM_PROMPT:
        unique_parts.insert(0, DEFAULT_SYSTEM_PROMPT)

    return "\\n\\n".join(unique_parts)'''
new = '''    unique_parts = _unique_prompt_parts(prompt_parts)
    if not unique_parts:
        return DEFAULT_SYSTEM_PROMPT
    if not has_custom_system_prompt and unique_parts[0] != DEFAULT_SYSTEM_PROMPT:
        unique_parts.insert(0, DEFAULT_SYSTEM_PROMPT)

    result = "\\n\\n".join(unique_parts)
    try:
        import logging

        logging.getLogger(__name__).info(
            "[PROMPT_DEBUG] system parts chars: system_skills=%d profile=%d resource_snapshot=%d persona_layer=%d persona=%d integration=%d total=%d",
            sum(len(p) for p in (_get_agent_skill_prompts(agent, "system") if agent is not None else [])),
            len(profile_prompt),
            len(resource_snapshot_prompt),
            len(PERSONA_IDENTITY_LAYER_PROMPT) if persona_prompts else 0,
            sum(len(p) for p in persona_prompts),
            len(integration_prompt),
            len(result),
        )
    except Exception:
        pass
    return result'''
assert old in src, "system.py anchor not found"
src = src.replace(old, new, 1)
sp.write_text(src, encoding="utf-8")
print("system.py patched")

# builder.py: log extra parts sizes
bp = pathlib.Path("backend/app/services/agent/prompts/builder.py")
b = bp.read_text(encoding="utf-8")
assert "PROMPT_DEBUG" not in b
anchor = '''    source_route_context = _build_current_source_route_context(agent, source="chat")
    if source_route_context:
        extra_prompt_parts.append(source_route_context)'''
add = '''
    try:
        import logging as _logging

        _logging.getLogger(__name__).info(
            "[PROMPT_DEBUG] extra_parts chars=%s catalog=%d",
            [len(p) for p in extra_prompt_parts],
            len(capability_catalog),
        )
    except Exception:
        pass'''
assert anchor in b, "builder anchor not found"
b = b.replace(anchor, anchor + add, 1)
bp.write_text(b, encoding="utf-8")
print("builder.py patched")