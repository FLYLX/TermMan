import pathlib

sp = pathlib.Path("backend/app/services/agent/prompts/system.py")
src = sp.read_text(encoding="utf-8")
dbg = '''    result = "\\n\\n".join(unique_parts)
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
orig = '''    return "\\n\\n".join(unique_parts)'''
assert dbg in src, "system dbg not found"
src = src.replace(dbg, orig, 1)
sp.write_text(src, encoding="utf-8")
print("system.py debug removed")

bp = pathlib.Path("backend/app/services/agent/prompts/builder.py")
b = bp.read_text(encoding="utf-8")
dbg2 = '''
    try:
        import logging as _logging

        _logging.getLogger(__name__).info(
            "[PROMPT_DEBUG] extra_parts chars=%s catalog=%d",
            [len(p) for p in extra_prompt_parts],
            len(capability_catalog),
        )
    except Exception:
        pass'''
assert dbg2 in b, "builder dbg not found"
b = b.replace(dbg2, "", 1)
bp.write_text(b, encoding="utf-8")
print("builder.py debug removed")