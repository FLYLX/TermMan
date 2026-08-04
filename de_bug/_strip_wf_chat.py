# -*- coding: utf-8 -*-
import re
from pathlib import Path

path = Path(r"backend\app\api\routes\chat.py")
src = path.read_text(encoding="utf-8")
orig = src

def rep(old, new, count=1):
    global src
    n = src.count(old)
    assert n == count, f"expected {count} match(es), found {n} for: {old[:80]!r}"
    src = src.replace(old, new)

def drop_block(sig_regex):
    """Drop a top-level def/class block from its signature line to the next top-level statement."""
    global src
    m = re.search(sig_regex, src, re.M)
    assert m, f"signature not found: {sig_regex}"
    start = m.start()
    nxt = re.search(r"^\S", src[m.end():], re.M)
    end = m.end() + nxt.start() if nxt else len(src)
    src = src[:start] + src[end:]

# --- 1. import ---
src = re.sub(r"^from app\.services\.agent\.task_workflow import task_workflow_manager\n", "", src, flags=re.M)

# --- 2. dead helper functions / class / regex ---
drop_block(r"^class PlannedTaskRuntime:")
drop_block(r"^def _plan_agent_task_titles\(")
drop_block(r"^def _complete_agent_task_plan\(")
drop_block(r"^def _mark_agent_task_plan_failed\(")
drop_block(r"^def _create_agent_task_plan\(")

# --- 3. _complete_confirmed_external_delivery gate ---
rep('''def _complete_confirmed_external_delivery(ticket_id: str) -> bool:
    can_finalize, _ = task_workflow_manager.can_finalize(ticket_id)
    if not can_finalize:
        return False
    ticket = reply_ticket_manager.get(ticket_id)''',
'''def _complete_confirmed_external_delivery(ticket_id: str) -> bool:
    ticket = reply_ticket_manager.get(ticket_id)''')

# --- 4. _finalize_stopped_turn: drop param + failed-mark call ---
rep('''    messages: list[dict[str, Any]],
    planned_task_runtime: PlannedTaskRuntime | None,
    reason: str,''',
'''    messages: list[dict[str, Any]],
    reason: str,''')
rep('''    _mark_agent_task_plan_failed(planned_task_runtime, reason)
    report = _generate_stopped_turn_report(''',
'''    report = _generate_stopped_turn_report(''')

# --- 5. dead planned_task_runtime init block ---
rep('''    planned_task_runtime = None
    if planned_task_runtime:
        planned_task_runtime.reply_ticket_id = reply_ticket.ticket_id
        reply_ticket_manager.mark_task_plan(
            reply_ticket.ticket_id,
            planned_task_runtime.request_id,
        )
        tools = select_tools_for_turn(
            agent.get_tools_for_litellm(),
            source=turn_source,
            agent=agent,
            reply_ticket_id=reply_ticket.ticket_id,
        )

''', '')

# --- 6. call-site kwargs ---
n = len(re.findall(r"^\s*planned_task_runtime=planned_task_runtime,\n", src, re.M))
assert n >= 4, f"expected >=4 planned_task_runtime kwargs, found {n}"
src = re.sub(r"^\s*planned_task_runtime=planned_task_runtime,\n", "", src, flags=re.M)

# --- 7. loop finalization simplification ---
rep('''            workflow_can_finalize, _ = task_workflow_manager.can_finalize(
                reply_ticket.ticket_id
            )
            action_recovery_only = bool(
                iteration_index == MAX_ITERATIONS and not workflow_can_finalize
            )
            finalization_only = bool(
                iteration_index == MAX_ITERATIONS and workflow_can_finalize
            )''',
'''            finalization_only = iteration_index == MAX_ITERATIONS''')

# --- 8. drop action_recovery_only branch ---
rep('''            if action_recovery_only:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "This is the action-recovery pass for an unfinished task. "
                            "Do not write a status summary, recommendation, promise, or next-step "
                            "sentence. Call exactly one concrete execution tool that advances the "
                            "current workflow. If the prior method failed, use a safe recovery "
                            "action now. Only mark blocked when user input, permission, or an "
                            "external prerequisite is truly required."
                        ),
                    }
                )
            elif finalization_only:''',
'''            if finalization_only:''')

# --- 9. abort try/except blocks (2x, different indent) ---
abort_pat = re.compile(
    r"(if AgentMessageQueue\.is_aborted\(item_id\):\n)"
    r"(?:[ ]+try:\n[ ]+task_workflow_manager\.update\(\n"
    r"[ ]+reply_ticket\.ticket_id,\n"
    r"[ ]+action=\"cancel\",\n"
    r"[ ]+note=\"User interrupted the task\.\",\n"
    r"[ ]+\)\n"
    r"[ ]+except Exception:\n"
    r"[ ]+pass\n)",
    re.M,
)
src, n = abort_pat.subn(r"\1", src)
assert n == 2, f"expected 2 abort blocks, found {n}"

# --- 10. workflow correction gate on final response ---
rep('''                if final_response:
                    can_finalize, workflow_correction = (
                        task_workflow_manager.can_finalize(reply_ticket.ticket_id)
                    )
                    if not can_finalize and not workflow_correction_used:
                        workflow_correction_used = True
                        messages.append(
                            {"role": "assistant", "content": final_response}
                        )
                        messages.append(
                            {
                                "role": "system",
                                "content": workflow_correction,
                            }
                        )
                        final_response = ""
                        continue

''', '')
rep('''    workflow_correction_used = False
''', '')

# --- 11. tool-loop recovery: drop workflow branch ---
rep('''                    workflow_can_finalize, _ = task_workflow_manager.can_finalize(
                        reply_ticket.ticket_id
                    )
                    if not workflow_can_finalize:
                        if not tool_loop_recovery_used:
                            messages.append(
                                {
                                    "role": "system",
                                    "content": (
                                        "The repeated tool call was blocked because it produced "
                                        "no new progress. Do not repeat the same workflow update, "
                                        "status check, or command. Choose a different concrete "
                                        "recovery action that advances the immutable main objective."
                                    ),
                                }
                            )
                            tool_loop_recovery_used = True
                            continue
                        terminal_session = agent_session_manager.get_or_create_session(
                            item_id,
                            str(handler.id),
                        )
                        continuation_scheduled = (
                            terminal_session.schedule_task_workflow_continuation(
                                reply_ticket.ticket_id
                            )
                        )
                        if continuation_scheduled:
                            _broadcast_agent_status(item_id, "idle")
                            yield _to_sse({"done": True})
                            return
                        for event in _finalize_stopped_turn(
                            agent=agent,
                            handler=handler,
                            item_id=item_id,
                            messages=messages,
                            reason=TOOL_LOOP_STOP_REASON,
                            prefers_chinese=_contains_cjk(message),
                            include_hidden_tool_results=include_hidden_tool_results,
                            reply_ticket_id=reply_ticket.ticket_id,
                        ):
                            yield _to_sse(event)
                        _broadcast_agent_status(item_id, "idle")
                        yield _to_sse({"done": True})
                        return
''', '')
rep('''    tool_loop_recovery_used = False
''', '')

# --- 12. record_tool_result on terminal input error ---
rep('''                            task_workflow_manager.record_tool_result(
                                reply_ticket.ticket_id,
                                tool_name=tool_name,
                                success=False,
                                result_summary=terminal_input_error,
                            )
''', '')

# --- 13. record_tool_call block ---
rep('''                if tool_name != "mcp_local_update_task_workflow":
                    task_workflow_manager.record_tool_call(
                        reply_ticket.ticket_id,
                        tool_name=tool_name,
                        command=str(tool_args.get("command") or ""),
                    )

''', '')

# --- 14. mark_job_started ---
rep('''                if is_background_job_started_result(result):
                    task_workflow_manager.mark_job_started(
                        reply_ticket.ticket_id,
                        command=str(tool_args.get("command") or ""),
                    )
                    clear_pending_terminal_continuation(''',
'''                if is_background_job_started_result(result):
                    clear_pending_terminal_continuation(''')

# --- 15. record_tool_result after tool run ---
rep('''                if tool_name != "mcp_local_update_task_workflow":
                    tool_success = bool(result.get("success", True)) and not (
                        result_text.strip().lower().startswith("error:")
                    )
                    task_workflow_manager.record_tool_result(
                        reply_ticket.ticket_id,
                        tool_name=tool_name,
                        success=tool_success,
                        result_summary=result_text,
                    )

''', '')

# --- 16. update_task_workflow arg normalization special case ---
rep('''    if tool_name == "mcp_local_update_task_workflow":
        # Notes are descriptive and often vary even when the model repeats the
        # same state transition without making progress.
        normalized = {
            key: normalized.get(key)
            for key in ("action", "step_index", "title")
            if normalized.get(key) not in (None, "")
        }

''', '')

# --- 17. recovery_inserted block ---
rep('''            recovery_inserted = any(
                tc.get("function", {}).get("name") == "mcp_local_update_task_workflow"
                and "insert_recovery_step" in str(tc.get("function", {}).get("arguments", ""))
                for tc in assistant_message.get("tool_calls", [])
            )
            if recovery_inserted:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "A recovery step was just created. You MUST immediately call "
                            "an execution tool (mcp_local_run_job or mcp_local_execute_command) "
                            "to start the recovery action. Do NOT reply with text, a plan, "
                            "or a status update. Call the tool NOW."
                        ),
                    }
                )

''', '')

# --- 18. budget exhausted continuation branch ---
rep('''        workflow_can_finalize, _ = task_workflow_manager.can_finalize(
            reply_ticket.ticket_id
        )
        if not workflow_can_finalize:
            terminal_session = agent_session_manager.get_or_create_session(
                item_id,
                str(handler.id),
            )
            continuation_scheduled = (
                terminal_session.schedule_task_workflow_continuation(
                    reply_ticket.ticket_id
                )
            )
            if continuation_scheduled:
                _broadcast_agent_status(item_id, "idle")
                yield _to_sse({"done": True})
                return
''', '')

# --- final sanity ---
remaining = [l for l in src.splitlines() if "task_workflow" in l or "PlannedTaskRuntime" in l or "planned_task_runtime" in l]
print("REMAINING REFS:", len(remaining))
for l in remaining[:20]:
    print("  ", l.strip()[:120])
path.write_text(src, encoding="utf-8")
print(f"chat.py patched: {len(orig)} -> {len(src)} chars")
