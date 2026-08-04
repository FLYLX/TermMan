# -*- coding: utf-8 -*-
import re
from pathlib import Path

path = Path(r"backend\app\services\agent\mcp\local_server.py")
src = path.read_text(encoding="utf-8")

def rep(old, new="", count=1):
    global src
    n = src.count(old)
    assert n == count, f"expected {count}, found {n}: {old[:70]!r}"
    src = src.replace(old, new)

def drop_method(sig):
    global src
    i = src.find(sig)
    assert i >= 0, f"method not found: {sig}"
    j = src.find("\n    def ", i + len(sig))
    assert j >= 0
    src = src[:i] + src[j+1:]

# --- 1. tool registrations ---
rep('''        self.register_tool(
            name="get_task_workflow",
            description="Read task workflow linked to current ticket.",
            input_schema={
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "string",
                        "description": "Current terminal item id.",
                    }
                },
                "required": ["item_id"],
            },
            handler=self._get_task_workflow,
            skip_memory=True,
        )
''')
i = src.find('        self.register_tool(\n            name="update_task_workflow",')
assert i >= 0
j = src.find("        self.register_tool(", i + 10)
assert j >= 0
src = src[:i] + src[j:]

# --- 2. handlers ---
drop_method("    def _get_task_workflow(self, args: dict) -> list:")
drop_method("    def _update_task_workflow(self, args: dict) -> list:")

# --- 3. flush robot path: drop workflow skip machinery ---
rep('''        first = robot_entries[0]
        robot_ticket = first.get("reply_ticket_id") or ""
        skip_robot = False
        if robot_ticket:
            try:
                from app.services.agent.task_workflow import task_workflow_manager

                if not task_workflow_manager.job_result_needs_new_turn(robot_ticket):
                    debug_log(
                        f"[LocalMCPServer] skip robot job-result: workflow "
                        f"finished/delivered for ticket={robot_ticket}, item={item_id}"
                    )
                    skip_robot = True
                else:
                    _wf = task_workflow_manager.get_by_ticket(robot_ticket)
                    if _wf and getattr(_wf, "report_sent_at", None) is not None:
                        debug_log(
                            f"[LocalMCPServer] skip robot job-result: report already "
                            f"sent for ticket={robot_ticket}, item={item_id}"
                        )
                        skip_robot = True
            except Exception:
                pass
        if not skip_robot:
            if len(robot_entries) == 1:
                _robot_wf_id = ""
                if robot_ticket:
                    try:
                        _rwf = task_workflow_manager.get_by_ticket(robot_ticket)
                        if _rwf:
                            _robot_wf_id = _rwf.workflow_id
                    except Exception:
                        pass
                message = server._format_background_job_robot_message(
                    first["command"],
                    first["result"],
                    reply_ticket_id=robot_ticket,
                    workflow_id=_robot_wf_id,
                )
            else:''',
'''        first = robot_entries[0]
        robot_ticket = first.get("reply_ticket_id") or ""
        if len(robot_entries) == 1:
            message = server._format_background_job_robot_message(
                first["command"],
                first["result"],
                reply_ticket_id=robot_ticket,
            )
        else:''')

# batch path indentation shift (was inside `if not skip_robot:`)
rep('''        else:
                message = _format_background_job_results_batch(robot_entries)
            message += server._plan_reminder(item_id, robot_ticket)
            delivered = server._deliver_background_job_to_robot(
                item_id=item_id,
                command=first["command"],
                result=first["result"],
                robot_job_context=first["robot_job_context"],
                pending_reply_id=first.get("pending_robot_reply_id") or "",
                reply_ticket_id=robot_ticket,
                message_override=message,
            )
            flushed_any = delivered or flushed_any
            if delivered and len(robot_entries) > 1:
                # The batch message covers every entry; clear the per-job
                # pending replies of the non-first entries so they do not
                # linger as orphaned queue items.
                for extra in robot_entries[1:]:
                    if extra.get("pending_robot_reply_id"):
                        server._clear_background_job_robot_reply(
                            robot_job_context=extra.get("robot_job_context"),
                            pending_reply_id=extra.get("pending_robot_reply_id") or "",
                        )
        else:
            # The owning workflow already finished/was delivered, so these
            # results will never be delivered to the robot conversation.
            # Clear the registered pending robot replies as well, otherwise
            # they linger forever as orphaned queue entries.
            for entry in robot_entries:
                try:
                    server._clear_background_job_robot_reply(
                        robot_job_context=entry.get("robot_job_context"),
                        pending_reply_id=entry.get("pending_robot_reply_id") or "",
                    )
                except Exception:
                    pass
            flushed_any = True''',
'''            message = _format_background_job_results_batch(robot_entries)
        message += server._plan_reminder(item_id, robot_ticket)
        delivered = server._deliver_background_job_to_robot(
            item_id=item_id,
            command=first["command"],
            result=first["result"],
            robot_job_context=first["robot_job_context"],
            pending_reply_id=first.get("pending_robot_reply_id") or "",
            reply_ticket_id=robot_ticket,
            message_override=message,
        )
        flushed_any = delivered or flushed_any
        if delivered and len(robot_entries) > 1:
            # The batch message covers every entry; clear the per-job
            # pending replies of the non-first entries so they do not
            # linger as orphaned queue items.
            for extra in robot_entries[1:]:
                if extra.get("pending_robot_reply_id"):
                    server._clear_background_job_robot_reply(
                        robot_job_context=extra.get("robot_job_context"),
                        pending_reply_id=extra.get("pending_robot_reply_id") or "",
                    )''')

# --- 4. other_entries guard ---
rep('''            entry_ticket = entry.get("reply_ticket_id") or ""
            if entry_ticket:
                try:
                    from app.services.agent.task_workflow import task_workflow_manager

                    if not task_workflow_manager.job_result_needs_new_turn(
                        entry_ticket
                    ):
                        debug_log(
                            f"[LocalMCPServer] skip job-result turn: owning workflow "
                            f"finished/delivered for ticket={entry_ticket}, item={item_id}"
                        )
                        flushed_any = True
                        continue
                    _wf_check = task_workflow_manager.get_by_ticket(entry_ticket)
                    if _wf_check and getattr(_wf_check, "report_sent_at", None) is not None:
                        debug_log(
                            f"[LocalMCPServer] skip job-result turn: report already sent "
                            f"for ticket={entry_ticket}, item={item_id}"
                        )
                        flushed_any = True
                        continue
                except Exception as exc:
                    debug_log(
                        f"[LocalMCPServer] job-result turn guard error: ticket={entry_ticket}, error={exc}"
                    )
            try:''',
'''            entry_ticket = entry.get("reply_ticket_id") or ""
            try:''')

# --- 5. list-jobs prompt tail ---
rep('''    lines.append(
        "If a task workflow is active, advance the affected workflow steps "
        "via mcp_local_update_task_workflow. If a plan is active (no workflow), "
        "sync it via mcp_local_update_plan (mark completed steps, start next, "
        "or clear when all done). Then verify and report per workflow/plan."
    )''',
'''    lines.append(
        "If a plan is active, sync it via mcp_local_update_plan (mark completed "
        "steps, start next, or clear when all done). Then verify and report."
    )''')

# --- 6. job-start workflow attach block ---
rep('''            if reply_ticket_id:
                try:
                    from app.services.agent.reply_ticket import reply_ticket_manager
                    from app.services.agent.task_workflow import task_workflow_manager

                    ticket = reply_ticket_manager.get(reply_ticket_id)
                    existing_wf = task_workflow_manager.get_by_ticket(reply_ticket_id)
                    if ticket is not None and existing_wf is None:
                        item_workflows = task_workflow_manager.list_resumable(
                            item_id=str(item_id),
                        )
                        active_wf = next(
                            (wf for wf in item_workflows if wf.status in {"active", "waiting_job", "verifying"}),
                            None,
                        )
                        if active_wf is not None:
                            task_workflow_manager.attach_ticket(
                                active_wf.workflow_id, reply_ticket_id
                            )
                except Exception as exc:
                    debug_log(
                        f"[LocalMCPServer] failed to register background job workflow: "
                        f"ticket={reply_ticket_id}, error={exc}"
                    )

            job_workflow_id = ""
            if reply_ticket_id:
                try:
                    from app.services.agent.task_workflow import task_workflow_manager as _twm
                    _wf = _twm.get_by_ticket(reply_ticket_id)
                    if _wf:
                        job_workflow_id = _wf.workflow_id
                        _twm.register_job_start(
                            reply_ticket_id,
                            command=command,
                            workflow_id=job_workflow_id,
                        )
                except Exception:
                    pass

''', '')

# --- 7. thread start kwargs ---
rep('''                reply_ticket_id=reply_ticket_id,
                workflow_id=job_workflow_id,
                pending_robot_reply_id=self._register_background_job_robot_reply(''',
'''                reply_ticket_id=reply_ticket_id,
                pending_robot_reply_id=self._register_background_job_robot_reply(''')

# --- 8. _attach_daemon_job_id_with_retry: method + caller ---
drop_method("    def _attach_daemon_job_id_with_retry(")
rep('''                    if reply_ticket_id and daemon_job_id:
                        threading.Thread(
                            target=self._attach_daemon_job_id_with_retry,
                            args=(reply_ticket_id,),
                            kwargs={"command": command, "daemon_job_id": daemon_job_id, "workflow_id": workflow_id},
                            daemon=True,
                        ).start()
                    result = self._poll_background_job_result(''',
'''                    result = self._poll_background_job_result(''')

# --- 9. thread signature ---
rep('''        reply_ticket_id: str = "",
        pending_robot_reply_id: str | None = None,
        workflow_id: str = "",
    ) -> None:''',
'''        reply_ticket_id: str = "",
        pending_robot_reply_id: str | None = None,
    ) -> None:''')

# --- 10. feedback kwarg + record_job_result block ---
rep('''            feedback = self._format_background_job_feedback(result, reply_ticket_id=reply_ticket_id, workflow_id=workflow_id)''',
'''            feedback = self._format_background_job_feedback(result, reply_ticket_id=reply_ticket_id)''')
rep('''            if reply_ticket_id:
                try:
                    from app.services.agent.task_workflow import task_workflow_manager

                    task_workflow_manager.record_job_result(
                        reply_ticket_id,
                        command=command,
                        success=(
                            bool(result.get("success"))
                            and result.get("exit_code") == 0
                            and not result.get("timed_out")
                            and not result.get("cancelled")
                        ),
                        result_summary=self._format_job_result(result),
                        daemon_job_id=str(result.get("job_id") or ""),
                        exit_code=result.get("exit_code"),
                        workflow_id=workflow_id,
                    )
                except Exception as exc:
                    debug_log(
                        f"[LocalMCPServer] failed to update task workflow from job: ticket={reply_ticket_id}, error={exc}"
                    )
''', '')

# --- 11. robot deliver path _rb_wf_id ---
rep('''            _rb_wf_id = ""
            if reply_ticket_id:
                try:
                    from app.services.agent.task_workflow import task_workflow_manager as _twm
                    _rbwf = _twm.get_by_ticket(reply_ticket_id)
                    if _rbwf:
                        _rb_wf_id = _rbwf.workflow_id
                except Exception:
                    pass
            message = message_override or self._format_background_job_robot_message(
                command, result, reply_ticket_id=reply_ticket_id, workflow_id=_rb_wf_id,
            )''',
'''            message = message_override or self._format_background_job_robot_message(
                command, result, reply_ticket_id=reply_ticket_id,
            )''')

# --- 12. _workflow_step_hint method ---
drop_method("    def _workflow_step_hint(self, reply_ticket_id: str, workflow_id: str) -> str:")

# --- 13. _plan_reminder workflow check ---
rep('''        plan = list(ticket.plan) if ticket is not None else []
        if not plan:
            return ""
        try:
            from app.services.agent.task_workflow import task_workflow_manager

            _wf = task_workflow_manager.get_by_ticket(reply_ticket_id)
            if _wf and _wf.status in {"cancelled", "failed"}:
                return ""
        except Exception:
            pass
        lines = ["", "当前计划（请根据本结果用 update_plan 同步进度）："]''',
'''        plan = list(ticket.plan) if ticket is not None else []
        if not plan:
            return ""
        lines = ["", "当前计划（请根据本结果用 update_plan 同步进度）："]''')

# --- 14. robot message formatter: drop workflow branch ---
rep('''    def _format_background_job_robot_message(self, command: str, result: dict, *, reply_ticket_id: str = "", workflow_id: str = "") -> str:
        status = "完成" if result.get("success") else "失败"
        has_workflow = bool(workflow_id)
        has_plan = bool(self._plan_reminder("", reply_ticket_id))
        request_boundary = self._job_callback_task_boundary(reply_ticket_id)
        step_hint = ""
        if has_workflow:
            step_hint = self._workflow_step_hint(reply_ticket_id, workflow_id)
            instruction = (
                "重要：任务工作流活跃。"
                + step_hint
                + "你的第一个动作必须是调用 "
                "mcp_local_update_task_workflow (action=complete_current_step 或 "
                "insert_recovery_step)，用上面的输出作为 evidence。"
                "不要先调 read_terminal_log 或 list_jobs。"
                "不要为中间结果发送 QQ 消息。"
                "只在到达汇报步骤、最终失败且无更多方法、或重大方向变更时才发 QQ。"
                "如果不需要回复用户，最终只输出 NRN 即可。"
            )
        elif has_plan:''',
'''    def _format_background_job_robot_message(self, command: str, result: dict, *, reply_ticket_id: str = "") -> str:
        status = "完成" if result.get("success") else "失败"
        has_plan = bool(self._plan_reminder("", reply_ticket_id))
        request_boundary = self._job_callback_task_boundary(reply_ticket_id)
        if has_plan:''')

# --- 15. feedback formatter: drop workflow branches ---
rep('''    def _format_background_job_feedback(self, result: dict, *, reply_ticket_id: str = "", workflow_id: str = "") -> str:
        has_workflow = bool(workflow_id)
        has_plan = bool(self._plan_reminder("", reply_ticket_id))
        if result.get("success"):
            if has_workflow:
                step_hint = self._workflow_step_hint(reply_ticket_id, workflow_id)
                header = (
                    "[Background terminal job completed]\\n"
                    "后台任务已完成。"
                    + step_hint
                    + "你的第一个动作必须是调用 mcp_local_update_task_workflow "
                    "(action=complete_current_step 或 insert_recovery_step)，"
                    "用下面的输出作为 evidence。"
                    "不要先调 read_terminal_log 或 list_jobs。"
                )
            elif has_plan:''',
'''    def _format_background_job_feedback(self, result: dict, *, reply_ticket_id: str = "") -> str:
        has_plan = bool(self._plan_reminder("", reply_ticket_id))
        if result.get("success"):
            if has_plan:''')
rep('''        step_hint = self._workflow_step_hint(reply_ticket_id, workflow_id) if has_workflow else ""
        if has_workflow:
            return (
                "[Background terminal job failed]\\n"
                + step_hint
                + "后台任务失败。调用 mcp_local_update_task_workflow "
                "(action=insert_recovery_step) 换方法继续，或确认无更多方法时汇报失败。\\n"
                f"Error: {result.get('error', 'daemon job failed')}\\n"
                f"command: {result.get('command', '')}"
            )
        if has_plan:''',
'''        if has_plan:''')

remaining = [l for l in src.splitlines() if "task_workflow" in l or "workflow_id" in l or "_workflow_step_hint" in l]
print("REMAINING:", len(remaining))
for l in remaining[:15]:
    print("  ", l.strip()[:110])
path.write_text(src, encoding="utf-8")
print("local_server patched")
