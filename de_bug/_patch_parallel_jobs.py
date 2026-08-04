import pathlib
p = pathlib.Path("backend/app/api/routes/chat.py")
src = p.read_text(encoding="utf-8")

# 1. flag init before the per-tool loop
loop_anchor = "            for tool_call in ordered_tool_calls:\n"
assert src.count(loop_anchor) == 1, f"loop anchor count={src.count(loop_anchor)}"
assert "background_job_started_this_iteration" not in src, "already patched"
src = src.replace(
    loop_anchor,
    "            background_job_started_this_iteration = False\n" + loop_anchor,
    1,
)

# 2. replace early return with flag + continue
early_return = """                if is_background_job_started_result(result):
                    task_workflow_manager.mark_job_started(
                        reply_ticket.ticket_id,
                        command=str(tool_args.get("command") or ""),
                    )
                    clear_pending_terminal_continuation(
                        item_id,
                        command=str(tool_args.get("command") or ""),
                    )
                    _broadcast_agent_status(item_id, "idle")
                    yield _to_sse({"done": True})
                    return
"""
deferred = """                if is_background_job_started_result(result):
                    task_workflow_manager.mark_job_started(
                        reply_ticket.ticket_id,
                        command=str(tool_args.get("command") or ""),
                    )
                    clear_pending_terminal_continuation(
                        item_id,
                        command=str(tool_args.get("command") or ""),
                    )
                    background_job_started_this_iteration = True
                    continue
"""
assert src.count(early_return) == 1, "early return anchor not unique/found"
src = src.replace(early_return, deferred, 1)

# 3. end the turn after the tool loop when a background job started
after_loop_anchor = "            if not assistant_message[\"tool_calls\"]:\n"
assert src.count(after_loop_anchor) == 1, f"after loop anchor count={src.count(after_loop_anchor)}"
src = src.replace(
    after_loop_anchor,
    """            if background_job_started_this_iteration:
                _broadcast_agent_status(item_id, "idle")
                yield _to_sse({"done": True})
                return

""" + after_loop_anchor,
    1,
)

p.write_text(src, encoding="utf-8")
print("chat.py parallel-job patch applied")