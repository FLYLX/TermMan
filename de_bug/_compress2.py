filepath = r"E:\dev\TermMan\dev\TermMan\backend\app\services\agent\mcp\local_server.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

changes = 0

# 1. read_chat_history
old = '''            description=(
                "Read recent TermMan chat/agent/terminal history for the current item. "
                "Use this when the user refers to previous work or context, such as "
                "'刚才', '前面', '之前', '继续', '上一个任务', '你忘了', or asks what was done. "
                "This is short-term evidence, not long-term memory."
            ),'''
new = '''            description="Read recent chat/agent/terminal history for context recovery.",'''
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print("1. read_chat_history: compressed")

# 2. get_task_workflow
old = '''            description=(
                "Read the authoritative task workflow linked to the current reply ticket. "
                "Use it whenever a multi-step task has changed method, hit an error, resumed "
                "after a background job, or you need to recover the main objective."
            ),'''
new = '''            description="Read task workflow linked to current ticket.",'''
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print("2. get_task_workflow: compressed")

# 3. list_terminal_filter_rules
old = '''            description="List all terminal filter rules for the current item, including terminal output -> Agent input filters and Agent -> terminal command output filters. Use this before adding or changing filters when the user asks what filtering rules exist.",'''
new = '''            description="List all terminal filter rules.",'''
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print("3. list_terminal_filter_rules: compressed")

# 4. delete_scheduled_task
old = '''            description=(
                "Delete one scheduled task by id. During scheduled execution, use this only "
                "after deciding the task is obsolete, invalid, unsafe, or permanently unable "
                "to succeed. Do not delete it for a transient failure."
            ),'''
new = '''            description="Delete a scheduled task by id.",'''
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print("4. delete_scheduled_task: compressed")

# 5. write_scheduled_task - shorten schema descriptions
old = '''                    "item_id": {
                        "type": "string",
                        "description": "Current terminal item id; injected automatically.",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Existing task id when updating; omit when creating.",
                    },
                    "name": {"type": "string", "description": "Short task name."},
                    "instruction": {
                        "type": "string",
                        "description": "Instruction sent to the Agent when the task runs.",
                    },'''
new = '''                    "item_id": {"type": "string", "description": "Item id (auto-injected)."},
                    "task_id": {"type": "string", "description": "Task id if updating."},
                    "name": {"type": "string", "description": "Task name."},
                    "instruction": {"type": "string", "description": "Agent instruction."},'''
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print("5. write_scheduled_task schema: compressed")

# 6. delete_scheduled_task schema
old = '''                    "item_id": {
                        "type": "string",
                        "description": "Current terminal item id; injected automatically.",
                    },
                    "task_id": {"type": "string", "description": "Scheduled task id."},
                    "reason": {
                        "type": "string",
                        "description": "Why the Agent decided to delete the task.",
                    },'''
new = '''                    "item_id": {"type": "string", "description": "Item id (auto-injected)."},
                    "task_id": {"type": "string", "description": "Task id."},
                    "reason": {"type": "string", "description": "Deletion reason."},'''
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print("6. delete_scheduled_task schema: compressed")

# 7. read_chat_history schema - shorten
old = '''                    "item_id": {"type": "string", "description": "Current terminal item id."},
                    "limit": {"type": "integer", "description": "Recent messages to return. Default 30, max 100.", "default": 30},
                    "offset": {"type": "integer", "description": "Skip this many newest messages before reading older history. Default 0.", "default": 0},
                    "query": {"type": "string", "description": "Optional case-insensitive substring filter."},
                    "include_summary": {"type": "boolean", "description": "Include the latest session summary when available. Default true.", "default": True},'''
new = '''                    "item_id": {"type": "string", "description": "Item id."},
                    "limit": {"type": "integer", "description": "Messages to return (default 30).", "default": 30},
                    "offset": {"type": "integer", "description": "Skip newest N messages.", "default": 0},
                    "query": {"type": "string", "description": "Substring filter."},
                    "include_summary": {"type": "boolean", "description": "Include session summary.", "default": True},'''
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print("7. read_chat_history schema: compressed")

with open(filepath, "w", encoding="utf-8", newline="\n") as f:
    f.write(content)
print(f"\nTotal changes: {changes}")