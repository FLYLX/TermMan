filepath = r"E:\dev\TermPaws\dev\TermPaws\backend\app\services\agent\mcp\local_server.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

old = '''            description=(
                "Create/update task workflow. 3+ step tasks: action=create with "
                "title='step1|step2|step3'. Continue existing workflow instead of "
                "duplicating. complete_current_step needs evidence. "
                "insert_recovery_step(title=...) on failure. "
                "cancel only when user abandons. After updating, call execution tool."
            ),'''

new = '''            description=(
                "Create/update task workflow. YOU MUST create a workflow FIRST "
                "before executing any task with 3+ steps (e.g. check->install->verify). "
                "Install/uninstall/configure/compile tasks ALWAYS qualify. "
                "action=create, title='step1|step2|step3'. "
                "Continue existing workflow, don't duplicate. "
                "complete_current_step needs evidence. "
                "insert_recovery_step(title=...) on failure. "
                "cancel only when user abandons. After updating, call execution tool."
            ),'''

if old in content:
    content = content.replace(old, new, 1)
    with open(filepath, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print("PATCHED: restored workflow creation imperative")
else:
    print("NOT FOUND")