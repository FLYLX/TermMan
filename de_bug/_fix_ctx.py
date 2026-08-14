# Fix 1: policy.py - all max_recent_messages to 6
filepath1 = r"E:\dev\TermPaws\dev\TermPaws\backend\app\services\agent\prompts\policy.py"
with open(filepath1, "r", encoding="utf-8") as f:
    c1 = f.read()

changes = 0
# CHAT: 10 -> 6
old = '''            max_recent_messages=10,'''
new = '''            max_recent_messages=6,'''
if old in c1:
    c1 = c1.replace(old, new, 1)
    changes += 1
    print("1. CHAT: 10 -> 6")

# TERMINAL_RAW_FEEDBACK: 4 -> 6
old = '''            max_recent_messages=4,'''
new = '''            max_recent_messages=6,'''
if old in c1:
    c1 = c1.replace(old, new, 1)
    changes += 1
    print("2. TERMINAL_RAW: 4 -> 6")

# TERMINAL_FILTERED (default): 8 -> 6
old = '''            max_recent_messages=8,'''
new = '''            max_recent_messages=6,'''
if old in c1:
    c1 = c1.replace(old, new, 1)
    changes += 1
    print("3. TERMINAL_FILTERED: 8 -> 6")

with open(filepath1, "w", encoding="utf-8", newline="\n") as f:
    f.write(c1)

# Fix 2 & 3: builder.py - skip agent_action, truncate verbose types
filepath2 = r"E:\dev\TermPaws\dev\TermPaws\backend\app\services\agent\prompts\builder.py"
with open(filepath2, "r", encoding="utf-8") as f:
    c2 = f.read()

# Add agent_action to NON_MODEL_CONTEXT_TYPES
old = '''NON_MODEL_CONTEXT_TYPES = {
    "agent_qq_reply",
}'''
new = '''NON_MODEL_CONTEXT_TYPES = {
    "agent_qq_reply",
    "agent_action",
}'''
if old in c2:
    c2 = c2.replace(old, new, 1)
    changes += 1
    print("4. Skip agent_action in context")

# Truncate verbose content in _event_to_model_message
old = '''    if message_type == "terminal_output" or role == "terminal":
        return {"role": "user", "content": f"{FILTERED_TERMINAL_LABEL}:\\n{content}"}

    if message_type in ASSISTANT_CONTEXT_TYPES or role == "assistant":
        return {"role": "assistant", "content": content}'''
new = '''    if message_type == "terminal_output" or role == "terminal":
        if len(content) > 200:
            content = content[:200] + "..."
        return {"role": "user", "content": f"{FILTERED_TERMINAL_LABEL}:\\n{content}"}

    if message_type in ASSISTANT_CONTEXT_TYPES or role == "assistant":
        if message_type == "agent_tool_result" and len(content) > 200:
            content = content[:200] + "..."
        return {"role": "assistant", "content": content}'''
if old in c2:
    c2 = c2.replace(old, new, 1)
    changes += 1
    print("5. Truncate tool_result/terminal_output to 200 chars")

with open(filepath2, "w", encoding="utf-8", newline="\n") as f:
    f.write(c2)

print(f"\nTotal: {changes} changes")