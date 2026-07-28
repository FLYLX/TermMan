filepath = r"E:\dev\TermMan\dev\TermMan\backend\app\services\agent\task_workflow.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

changes = 0

# 1. Fix misleading error message in mark_ready_to_report
old = '''                    return (
                        False,
                        f"Cannot report completion while workflow steps remain incomplete: {titles}. "
                        "You must execute the remaining steps first (run the verification command "
                        "via run_job), then call complete_current_step with the result, "
                        "then mark_ready_to_report.",
                    )'''
new = '''                    return (
                        False,
                        f"Steps still incomplete: {titles}. "
                        "Run the verification command, then call complete_current_step with evidence. "
                        "Completing the LAST step auto-transitions to ready_to_report.",
                    )'''
if old in content:
    content = content.replace(old, new, 1)
    changes += 1
    print("1. Fixed mark_ready_to_report error message")

# 2. Fix verification step rejection message - add guidance
old2 = '''                    return (
                        False,
                        "Verification steps require fresh evidence from this run: call a "
                        "check/verify tool now and use its real output as evidence before "
                        "completing this step.",
                    )'''
new2 = '''                    return (
                        False,
                        "Verification step needs evidence: run the check command via run_job first, "
                        "then call complete_current_step(note=<command output>).",
                    )'''
if old2 in content:
    content = content.replace(old2, new2, 1)
    changes += 1
    print("2. Fixed verification step rejection message")

with open(filepath, "w", encoding="utf-8", newline="\n") as f:
    f.write(content)
print(f"Total: {changes} changes")