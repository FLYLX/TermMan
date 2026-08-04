import io

path = r"E:\dev\TermMan\dev\TermMan\backend\app\services\agent\session.py"
with io.open(path, "r", encoding="utf-8") as handle:
    text = handle.read()

old_1 = '''                try:
                    for skill in agent.match_skills(
                        (input_msg.query or effective_terminal_content or "")[:500]
                    ):
                        action = getattr(skill, "action", None)
                        prompt = str(getattr(action, "prompt", "") or "").strip()
                        if prompt:
                            system_parts.append(prompt)
                except Exception:
                    pass'''
new_1 = '''                try:
                    from app.services.agent.capability_state import ensure_loaded
                    from app.services.agent.tool_selection import (
                        TERMINAL_GUIDE_IDS,
                        loaded_guide_skills,
                    )

                    ensure_loaded(self.item_id, guides=TERMINAL_GUIDE_IDS)
                    for skill in loaded_guide_skills(agent, self.item_id):
                        action = getattr(skill, "action", None)
                        prompt = str(getattr(action, "prompt", "") or "").strip()
                        if prompt:
                            system_parts.append(prompt)
                except Exception:
                    pass'''
assert text.count(old_1) == 1, "s1 anchor=%d" % text.count(old_1)
text = text.replace(old_1, new_1, 1)

old_2 = '''        effective_skill_query = skill_query if skill_query is not None else query
        skills = agent.match_skills(effective_skill_query) if effective_skill_query else []
        for skill in skills:'''
new_2 = '''        from app.services.agent.tool_selection import loaded_guide_skills

        skills = loaded_guide_skills(agent, self.item_id)
        for skill in skills:'''
assert text.count(old_2) == 1, "s2 anchor=%d" % text.count(old_2)
text = text.replace(old_2, new_2, 1)

with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(text)
print("session.py patched")