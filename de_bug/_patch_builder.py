import io

path = r"E:\dev\TermPaws\dev\TermPaws\backend\app\services\agent\prompts\builder.py"
with io.open(path, "r", encoding="utf-8") as handle:
    text = handle.read()

# 1. _build_skill_prompt signature: add item_id param
old_sig = '''def _build_skill_prompt(
    agent: "Agent",
    query: str,
    *,
    force_skill_ids: set[str] | None = None,'''
new_sig = '''def _build_skill_prompt(
    agent: "Agent",
    query: str,
    *,
    item_id: str = "",
    force_skill_ids: set[str] | None = None,'''
assert text.count(old_sig) == 1, "sig anchor=%d" % text.count(old_sig)
text = text.replace(old_sig, new_sig, 1)

# 2. remove regex skill matching; start from always-on skills only
old_match = '''    skills = agent.match_skills(query) if query else []
    existing_skill_ids = {skill.skill_id for skill in skills}'''
new_match = '''    skills: list = []
    existing_skill_ids: set[str] = set()'''
assert text.count(old_match) == 1, "match anchor=%d" % text.count(old_match)
text = text.replace(old_match, new_match, 1)

# 3. after force_skill_ids block, add progressively loaded guides
old_force_tail = '''                skills.append(forced_skill)
                existing_skill_ids.add(forced_skill.skill_id)
    skills = integration_filter_skills(skills, agent)'''
new_force_tail = '''                skills.append(forced_skill)
                existing_skill_ids.add(forced_skill.skill_id)
    if item_id:
        from app.services.agent.tool_selection import loaded_guide_skills

        for skill in loaded_guide_skills(agent, item_id):
            if skill.skill_id not in existing_skill_ids:
                skills.append(skill)
                existing_skill_ids.add(skill.skill_id)
    skills = integration_filter_skills(skills, agent)'''
assert text.count(old_force_tail) == 1, "force anchor=%d" % text.count(old_force_tail)
text = text.replace(old_force_tail, new_force_tail, 1)

# 4. chat turn builder: inject catalog + pass item_id
old_chat = '''    extra_prompt_parts: list[str] = []
    source_route_context = _build_current_source_route_context(agent, source="chat")
    if source_route_context:
        extra_prompt_parts.append(source_route_context)'''
new_chat = '''    extra_prompt_parts: list[str] = []
    capability_catalog = build_capability_catalog(agent, source="chat")
    if capability_catalog:
        extra_prompt_parts.append(capability_catalog)
    source_route_context = _build_current_source_route_context(agent, source="chat")
    if source_route_context:
        extra_prompt_parts.append(source_route_context)'''
assert text.count(old_chat) == 1, "chat anchor=%d" % text.count(old_chat)
text = text.replace(old_chat, new_chat, 1)

old_chat_call = '''            "content": _build_skill_prompt(
                agent,
                effective_query,
                extra_prompt_parts=extra_prompt_parts,'''
new_chat_call = '''            "content": _build_skill_prompt(
                agent,
                effective_query,
                item_id=item_id,
                extra_prompt_parts=extra_prompt_parts,'''
assert text.count(old_chat_call) == 1, "chatcall anchor=%d" % text.count(old_chat_call)
text = text.replace(old_chat_call, new_chat_call, 1)

# 5. terminal turn builder: preload terminal capabilities + pass item_id
old_term = '''    extra_prompt_parts: list[str] = []
    source_route_context = _build_current_source_route_context(agent, source="terminal")
    if source_route_context:
        extra_prompt_parts.append(source_route_context)'''
new_term = '''    extra_prompt_parts: list[str] = []
    if item_id:
        from app.services.agent.capability_state import ensure_loaded
        from app.services.agent.tool_selection import (
            TERMINAL_GUIDE_IDS,
            TERMINAL_TOOLSET,
        )

        ensure_loaded(item_id, tools=TERMINAL_TOOLSET, guides=TERMINAL_GUIDE_IDS)
    source_route_context = _build_current_source_route_context(agent, source="terminal")
    if source_route_context:
        extra_prompt_parts.append(source_route_context)'''
assert text.count(old_term) == 1, "term anchor=%d" % text.count(old_term)
text = text.replace(old_term, new_term, 1)

old_term_call = '''            "content": _build_skill_prompt(
                agent,
                effective_query,
                force_skill_ids={TERMINAL_CRITICAL_ALERT_SKILL_ID}'''
new_term_call = '''            "content": _build_skill_prompt(
                agent,
                effective_query,
                item_id=item_id,
                force_skill_ids={TERMINAL_CRITICAL_ALERT_SKILL_ID}'''
assert text.count(old_term_call) == 1, "termcall anchor=%d" % text.count(old_term_call)
text = text.replace(old_term_call, new_term_call, 1)

# 6. import build_capability_catalog at top of builder module (lazy-safe import inside function instead)
old_import = '''    extra_prompt_parts: list[str] = []
    capability_catalog = build_capability_catalog(agent, source="chat")'''
new_import = '''    extra_prompt_parts: list[str] = []
    from app.services.agent.tool_selection import build_capability_catalog

    capability_catalog = build_capability_catalog(agent, source="chat")'''
assert text.count(old_import) == 1, "import anchor=%d" % text.count(old_import)
text = text.replace(old_import, new_import, 1)

with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(text)
print("builder.py patched")