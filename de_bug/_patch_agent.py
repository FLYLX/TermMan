import io

path = r"E:\dev\TermPaws\dev\TermPaws\backend\app\services\agent\agent.py"
with io.open(path, "r", encoding="utf-8") as handle:
    text = handle.read()

old = '''    def match_skills(self, query: str) -> list[SkillDefinition]:
        matched = []
        query_lower = query.lower()

        for skill in self._skills.values():
            if skill.trigger and skill.trigger.patterns:
                for pattern in skill.trigger.patterns:
                    try:
                        if re.search(pattern, query_lower):
                            matched.append(skill)
                            break
                    except re.error:
                        if pattern.lower() in query_lower:
                            matched.append(skill)
                            break
            else:
                keywords = [skill.skill_id.lower(), skill.name.lower()]
                if skill.description:
                    keywords.extend(skill.description.lower().split())
                for kw in keywords:
                    if kw in query_lower:
                        matched.append(skill)
                    break

        return matched'''
new = '''    def match_skills(self, query: str) -> list[SkillDefinition]:
        """Deprecated compatibility shim.

        Regex/keyword-based skill matching was removed: skill guides are now
        exposed through the capability catalog and loaded on demand by the
        agent (see app.services.agent.tool_selection). Always returns [].
        """
        del query
        return []'''
assert text.count(old) == 1, "anchor=%d" % text.count(old)
text = text.replace(old, new, 1)

with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(text)
print("agent.py patched")