import pathlib, sys
sys.path.insert(0, r"E:\dev\TermPaws\dev\TermPaws\de_bug")
import importlib.util

root = pathlib.Path(r"E:\dev\TermPaws\dev\TermPaws")

# reuse delete_test_function logic inline
import re
def delete_test_function(rel, test_name):
    p = root / rel
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    start = None
    for i, ln in enumerate(lines):
        if re.match(rf"^(async )?def {re.escape(test_name)}\(", ln):
            start = i
            break
    assert start is not None, f"{test_name} not found"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^(async def |def |class |@)", lines[j]):
            end = j
            break
    while end < len(lines) and lines[end].strip() == "":
        end += 1
    new = lines[:start] + lines[end:]
    text = "".join(new)
    text = re.sub(r"\n{4,}(?=(async )?def |class |@)", "\n\n\n", text)
    p.write_text(text, encoding="utf-8")
    print(f"deleted {test_name}")

rel = r"backend\tests\services\test_agent_state_persistence.py"
delete_test_function(rel, "test_workflow_persists_and_restores_with_interruption_normalized")
delete_test_function(rel, "test_final_workflow_is_not_restored")

p = root / r"backend\tests\api\routes\test_chat_timeline.py"
text = p.read_text(encoding="utf-8")

old_assert = '''        assert len(workflows) == 1
        assert workflows[0]["status"] == "failed"
        assert any(COMMAND_DISPATCH_FAILURE_MESSAGE in chunk for chunk in chunks)'''
new_assert = '''        assert any(COMMAND_DISPATCH_FAILURE_MESSAGE in chunk for chunk in chunks)'''
assert text.count(old_assert) == 1
text = text.replace(old_assert, new_assert)

n = text.count("mcp_local_update_task_workflow")
assert n == 5, n
text = text.replace("mcp_local_update_task_workflow", "mcp_local_run_job")
text = text.replace(
    "def test_tool_loop_detection_ignores_changing_workflow_notes",
    "def test_tool_loop_detection_ignores_changing_notes",
)
p.write_text(text, encoding="utf-8")
print("test_chat_timeline.py final cleanup done")
