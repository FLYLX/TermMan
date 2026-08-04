import io

path = r"E:\dev\TermMan\dev\TermMan\backend\app\api\routes\chat.py"
with io.open(path, "r", encoding="utf-8") as handle:
    text = handle.read()

# A. simple web endpoint: drop regex skill matching
old_a = '''    matched_skills = agent.match_skills(message)
    tools = select_tools_for_turn(
        agent.get_tools_for_litellm(),
        source="web",
        query=message,
        agent=agent,
    )'''
new_a = '''    matched_skills: list = []
    tools = select_tools_for_turn(
        agent.get_tools_for_litellm(),
        source="web",
        agent=agent,
    )'''
assert text.count(old_a) == 1, "A anchor=%d" % text.count(old_a)
text = text.replace(old_a, new_a, 1)

# B. streaming endpoint: drop regex matching + keyword query
old_b = '''    matched_skills = agent.match_skills(message)
    tool_selection_query = _build_tool_selection_query(message, history)
    tools = select_tools_for_turn(
        agent.get_tools_for_litellm(),
        source="qq" if normalized_source_type == SOURCE_QQ else "web",
        query=tool_selection_query,
        agent=agent,
        reply_ticket_id=reply_ticket.ticket_id,
    )'''
new_b = '''    matched_skills: list = []
    turn_source = "qq" if normalized_source_type == SOURCE_QQ else "web"
    tools = select_tools_for_turn(
        agent.get_tools_for_litellm(),
        source=turn_source,
        agent=agent,
        reply_ticket_id=reply_ticket.ticket_id,
    )'''
assert text.count(old_b) == 1, "B anchor=%d" % text.count(old_b)
text = text.replace(old_b, new_b, 1)

# C. dead planned_task_runtime block: drop stale query arg
old_c = '''        tools = select_tools_for_turn(
            agent.get_tools_for_litellm(),
            source="qq" if normalized_source_type == SOURCE_QQ else "web",
            query=tool_selection_query,
            agent=agent,
            reply_ticket_id=reply_ticket.ticket_id,
        )'''
new_c = '''        tools = select_tools_for_turn(
            agent.get_tools_for_litellm(),
            source=turn_source,
            agent=agent,
            reply_ticket_id=reply_ticket.ticket_id,
        )'''
assert text.count(old_c) == 1, "C anchor=%d" % text.count(old_c)
text = text.replace(old_c, new_c, 1)

# D. refresh tools each iteration so prepare_capabilities takes effect
old_d = '''            iteration_tools = [] if finalization_only else tools'''
new_d = '''            iteration_tools = (
                []
                if finalization_only
                else select_tools_for_turn(
                    agent.get_tools_for_litellm(),
                    source=turn_source,
                    agent=agent,
                    reply_ticket_id=reply_ticket.ticket_id,
                )
            )'''
assert text.count(old_d) == 1, "D anchor=%d" % text.count(old_d)
text = text.replace(old_d, new_d, 1)

# E. other endpoint: drop regex matching
old_e = '''        matched_skills = agent.match_skills(request.message)'''
new_e = '''        matched_skills: list = []'''
assert text.count(old_e) == 1, "E anchor=%d" % text.count(old_e)
text = text.replace(old_e, new_e, 1)

# F. diagnostic endpoint: list all skills instead of regex match
old_f = '''        matched = agent.match_skills(query)'''
new_f = '''        matched = list(agent.get_skills())'''
assert text.count(old_f) == 1, "F anchor=%d" % text.count(old_f)
text = text.replace(old_f, new_f, 1)

with io.open(path, "w", encoding="utf-8", newline="\n") as handle:
    handle.write(text)
print("chat.py patched")