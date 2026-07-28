import re

filepath = r"E:\dev\TermMan\dev\TermMan\backend\app\services\agent\mcp\local_server.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

changes = 0

# 1. Compress update_task_workflow description (1451 -> ~350 chars)
old_desc = '''            description=(
                "Create or update the authoritative task workflow. "
                "When you receive a task that will take 3 or more steps, YOU must call "
                "this tool with action=create FIRST to create a workflow with planned steps. "
                "Install/uninstall/configure/upgrade tasks that end with a verification "
                "step ALWAYS qualify (e.g. check -> install -> verify = 3 steps), so create "
                "a workflow for them. "
                "Use title='step1|step2|step3' to define steps (pipe-separated). "
                "Use note for the main objective. "
                "The user sees workflow progress in the task queue, so always create one "
                "for multi-step tasks. "
                "If non-final workflow(s) already exist for this item, review "
                "the listed workflows: continue the matching one with the update actions "
                "instead of creating a duplicate; only retry with force_new=true when the "
                "task is genuinely different. "
                "The main objective cannot be replaced. Complete the current step only "
                "after evidence. When a step fails, use insert_recovery_step(title='new method') "
                "which cancels the failed step, rewrites the next step to the new method, and "
                "resets all subsequent steps to pending -- keeping the plan short and linear. "
                "Mark blocked only when user or external input is genuinely required. "
                "Action=cancel cancels the whole objective and is allowed only when the user "
                "explicitly abandons it; use cancel_job to stop an obsolete execution while "
                "keeping the main objective active. Updating workflow state is not execution, "
                "so call the concrete terminal/job tool immediately afterward."
            ),'''
new_desc = '''            description=(
                "Create/update task workflow. 3+ step tasks: action=create with "
                "title='step1|step2|step3'. Continue existing workflow instead of "
                "duplicating. complete_current_step needs evidence. "
                "insert_recovery_step(title=...) on failure. "
                "cancel only when user abandons. After updating, call execution tool."
            ),'''
if old_desc in content:
    content = content.replace(old_desc, new_desc, 1)
    changes += 1
    print("1. update_task_workflow desc: compressed")
else:
    print("1. update_task_workflow desc: NOT FOUND")

# 2. Compress force_new schema description
old_fn = '''                    "force_new": {
                        "type": "boolean",
                        "description": (
                            "Only for action=create: set true to create a new workflow "
                            "even though non-final workflow(s) already exist for this item, "
                            "after reviewing them and confirming the task is genuinely different. "
                            "Never use it to duplicate an existing task."
                        ),
                    },'''
new_fn = '''                    "force_new": {
                        "type": "boolean",
                        "description": "Create new workflow even if existing ones present.",
                    },'''
if old_fn in content:
    content = content.replace(old_fn, new_fn, 1)
    changes += 1
    print("2. force_new schema: compressed")
else:
    print("2. force_new schema: NOT FOUND")

# 3. Compress get_terminal_status description
old_ts = '''            description=(
                "Read the authoritative live terminal state. The terminal is open only when "
                "the Daemon terminal process is active and Backend is currently joined to the "
                "Item Socket Room as a permanent subscriber. Use this whenever the user asks "
                "whether the terminal is open, connected, online, or usable. Never infer that "
                "state from chat history, logs, Item status, or cached handlers."
            ),'''
new_ts = '''            description="Read live terminal state (open/connected/usable).",'''
if old_ts in content:
    content = content.replace(old_ts, new_ts, 1)
    changes += 1
    print("3. get_terminal_status desc: compressed")
else:
    print("3. get_terminal_status desc: NOT FOUND")

with open(filepath, "w", encoding="utf-8", newline="\n") as f:
    f.write(content)
print(f"\nTotal changes: {changes}")