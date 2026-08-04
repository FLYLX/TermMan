import pathlib, re, sys

root = pathlib.Path(r"E:\dev\TermMan\dev\TermMan")

def delete_test_function(rel, test_name):
    """Delete a top-level test function (with optional decorators before NEXT test kept intact)."""
    p = root / rel
    lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
    start = None
    for i, ln in enumerate(lines):
        if re.match(rf"^(async )?def {re.escape(test_name)}\(", ln):
            start = i
            break
    assert start is not None, f"{test_name} not found in {rel}"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if re.match(r"^(async def |def |class |@)", lines[j]):
            end = j
            break
    # trim trailing blank lines we leave behind (keep max 2 blank between defs)
    while end < len(lines) and lines[end].strip() == "":
        end += 1
    # back off: keep exactly two blank lines before next def
    cut = end
    # find where blanks before next def start
    k = start
    # actually simpler: remove [start, end) then collapse >2 blank lines at join point
    new = lines[:start] + lines[end:]
    text = "".join(new)
    text = re.sub(r"\n{4,}(?=(async )?def |class |@)", "\n\n\n", text)
    p.write_text(text, encoding="utf-8")
    print(f"deleted {test_name} from {rel} (lines {start+1}-{end})")

# ---------- 1. delete whole workflow test files ----------
for rel in (r"backend\tests\api\routes\test_task_workflows.py",
            r"backend\tests\services\test_task_workflow.py",
            r"backend\tests\services\test_local_task_workflow.py",
            r"backend\tests\services\test_java_install_workflow_e2e.py"):
    fp = root / rel
    assert fp.exists(), rel
    fp.unlink()
    print("deleted file:", rel)

# ---------- 2. test_chat_timeline.py ----------
rel = r"backend\tests\api\routes\test_chat_timeline.py"
for name in [
    "test_agent_task_plan_records_reply_origin",
    "test_vague_start_messages_and_status_questions_do_not_create_tasks",
    "test_agent_task_plan_creates_task_workflow",
    "test_agent_task_plan_inserts_source_change_into_running_workflow",
    "test_repeated_install_request_reuses_same_active_workflow",
    "test_repeated_task_reuses_matching_workflow_and_preserves_job_progress",
    "test_finish_then_tell_me_keeps_task_active_and_enables_final_only",
    "test_cancel_current_execution_does_not_cancel_main_objective",
    "test_terminal_unavailable_task_reports_failure_and_removes_queue_entry",
    "test_qq_task_plan_uses_current_message_instead_of_robot_context_card",
    "test_stopped_web_task_reports_failure_then_removes_queue_entry",
    "test_agent_task_workflow_does_not_depend_on_vector_memory_write",
]:
    delete_test_function(rel, name)

p = root / rel
text = p.read_text(encoding="utf-8")

stub = '    monkeypatch.setattr(chat_route, "_create_agent_task_plan", lambda *args, **kwargs: None)\n'
n = text.count(stub)
assert n == 18, f"expected 18 stubs, found {n}"
text = text.replace(stub, "")

block_titles = '''    monkeypatch.setattr(
        chat_route,
        "_plan_agent_task_titles",
        lambda *_args, **_kwargs: ["\u68c0\u67e5\u7cfb\u7edf", "\u5b89\u88c5 Java", "\u9a8c\u8bc1\u7248\u672c"],
    )
'''
assert text.count(block_titles) == 1, "titles block"
text = text.replace(block_titles, "")

block_create = '''    monkeypatch.setattr(
        chat_route,
        "_create_agent_task_plan",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("internal callback must not create a new user task plan")
        ),
    )
'''
assert text.count(block_create) == 1, "create block"
text = text.replace(block_create, "")

# remove any remaining task_workflow_manager lines (resets / imports)
out_lines = []
removed = 0
for ln in text.splitlines(keepends=True):
    if "task_workflow_manager" in ln:
        removed += 1
        continue
    out_lines.append(ln)
text = "".join(out_lines)
p.write_text(text, encoding="utf-8")
print(f"test_chat_timeline.py cleaned: stubs={n}, wf lines removed={removed}")

# ---------- 3. test_agent_state_persistence.py ----------
rel = r"backend\tests\services\test_agent_state_persistence.py"
delete_test_function(rel, "test_watchdog_closes_stale_workflow_and_reports")
delete_test_function(rel, "test_watchdog_keeps_fresh_workflow")
p = root / rel
text = p.read_text(encoding="utf-8")
marker = "def _make_waiting_job_workflow("
idx = text.index(marker)
# cut back to the two blank lines after previous test
text = text[:idx].rstrip() + "\n"
text = text.replace("from app.services.agent import task_workflow as task_workflow_module\n", "")
text = text.replace("from app.services.agent.task_workflow import task_workflow_manager\n", "")
p.write_text(text, encoding="utf-8")
print("test_agent_state_persistence.py truncated + imports removed")

# ---------- 4. test_reply_ticket_lifecycle.py ----------
rel = r"backend\tests\services\test_reply_ticket_lifecycle.py"
delete_test_function(rel, "test_intermediate_delivery_cannot_close_active_task_workflow")
p = root / rel
text = p.read_text(encoding="utf-8")
text = text.replace("from app.services.agent.task_workflow import task_workflow_manager\n", "")
text = text.replace("    task_workflow_manager.reset()\n", "")
p.write_text(text, encoding="utf-8")
print("test_reply_ticket_lifecycle.py cleaned")

# ---------- 5. test_local_mcp_server.py ----------
delete_test_function(
    r"backend\tests\services\test_local_mcp_server.py",
    "test_background_run_job_registers_task_workflow_only_after_start",
)

# ---------- 6. test_agent_session_workflow.py ----------
rel = r"backend\tests\services\test_agent_session_workflow.py"
delete_test_function(rel, "test_schedule_task_workflow_continuation_is_internal_and_bounded")
p = root / rel
text = p.read_text(encoding="utf-8")
text = text.replace("from app.services.agent.task_workflow import task_workflow_manager\n", "")
n = text.count("mcp_local_update_task_workflow")
assert n == 3, n
text = text.replace("mcp_local_update_task_workflow", "mcp_local_run_job")
p.write_text(text, encoding="utf-8")
print("test_agent_session_workflow.py cleaned")

# ---------- 7. test_tool_markup.py ----------
p = root / r"backend\tests\services\test_tool_markup.py"
text = p.read_text(encoding="utf-8")
n = text.count("mcp_local_update_task_workflow")
assert n == 3, n
text = text.replace("mcp_local_update_task_workflow", "mcp_local_run_job")
p.write_text(text, encoding="utf-8")
print("test_tool_markup.py replaced")

# ---------- 8. test_tool_grounding.py ----------
p = root / r"backend\tests\services\test_tool_grounding.py"
text = p.read_text(encoding="utf-8")
n = text.count("mcp_local_update_task_workflow")
assert n == 2, n
text = text.replace("mcp_local_update_task_workflow", "mcp_local_list_jobs")
p.write_text(text, encoding="utf-8")
print("test_tool_grounding.py replaced")

# ---------- 9. test_robot_mcp_server.py ----------
p = root / r"backend\tests\services\test_robot_mcp_server.py"
text = p.read_text(encoding="utf-8")
n = text.count("mcp_local_update_task_workflow")
assert n >= 1, n
text = text.replace("mcp_local_update_task_workflow", "mcp_local_run_job")
p.write_text(text, encoding="utf-8")
print(f"test_robot_mcp_server.py replaced ({n})")

# ---------- 10. test_tool_selection.py ----------
p = root / r"backend\tests\services\test_tool_selection.py"
text = p.read_text(encoding="utf-8")
for ln in ('    _tool("mcp_local_get_task_workflow"),\n',
           '    _tool("mcp_local_update_task_workflow"),\n'):
    assert text.count(ln) == 1, ln
    text = text.replace(ln, "")
p.write_text(text, encoding="utf-8")
print("test_tool_selection.py cleaned")

# ---------- 11. test_agent_runtime_guards.py ----------
p = root / r"backend\tests\services\test_agent_runtime_guards.py"
text = p.read_text(encoding="utf-8")
ln = '    assert "mcp_local_get_task_workflow" in (terminal_mcp.action.prompt or "")\n'
assert text.count(ln) == 1
text = text.replace(ln, "")
p.write_text(text, encoding="utf-8")
print("test_agent_runtime_guards.py cleaned")

print("STAGE2 DONE")
