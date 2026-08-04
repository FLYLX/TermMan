# -*- coding: utf-8 -*-
import re
from pathlib import Path

path = Path(r"backend\app\services\agent\session.py")
src = path.read_text(encoding="utf-8")

def rep(old, new="", count=1):
    global src
    n = src.count(old)
    assert n == count, f"expected {count}, found {n}: {old[:70]!r}"
    src = src.replace(old, new)

# 1. import (both occurrences)
import re as _re
src = _re.sub(r"^from app\.services\.agent\.task_workflow import task_workflow_manager\n", "", src, flags=_re.M)

# 2. workflow job lookup
rep('''        try:
            for workflow in task_workflow_manager.list_resumable(item_id=self.item_id):
                for wf_job in workflow.jobs:
                    if (
                        wf_job.status == "running"
                        and self._normalize_text(wf_job.command) == normalized_command
                    ):
                        return {
                            "command": wf_job.command,
                            "elapsed_seconds": 0,
                            "source": "workflow",
                            "job_id": wf_job.workflow_job_id,
                        }

        except Exception:
            pass

        return None''',
'''        return None''')

# 3. pending reply waiting: call + method
rep("        self._update_pending_reply_waiting(pending)\n")
rep('''    def _update_pending_reply_waiting(self, pending: PendingCommand) -> None:
        parsed = self._parse_terminal_relay_command(pending.command)
        if not parsed or not pending.reply_ticket_id:
            return
        target_player, question = parsed
        try:
            task_workflow_manager.mark_waiting(
                pending.reply_ticket_id,
                awaiting_kind="minecraft_player",
                awaiting_key=target_player,
                note=question,
            )
            logger.info(
                "[AgentSession] Task workflow now awaits Minecraft player item=%s "
                "ticket=%s player=%s question=%s",
                self.item_id,
                pending.reply_ticket_id,
                target_player,
                question[:160],
            )
        except Exception as exc:
            logger.warning(
                "[AgentSession] Failed to update workflow awaiting target: %s",
                exc,
            )

''')

# 4. terminal reply delivery gate
rep('''                    can_fin, _ = task_workflow_manager.can_finalize(ticket_id)
                    if can_fin:
                        reply_ticket_manager.mark_delivered(ticket_id)
                    return True''',
'''                    reply_ticket_manager.mark_delivered(ticket_id)
                    return True''')

# 5. fail path workflow cancel
rep('''            task_workflow_manager.update(
                ticket_id,
                action="cancel",
                note=str(reason or report)[:2000],
            )
            reply_ticket_manager.mark_failed(ticket_id, reason or report)''',
'''            reply_ticket_manager.mark_failed(ticket_id, reason or report)''')

# 6. primary ticket selection
rep('''        # Pick primary reply_ticket: prefer one with an active workflow
        primary_ticket = ""
        try:
            from app.services.agent.task_workflow import task_workflow_manager
            for msg in batch:
                ticket = str(msg.reply_ticket_id or "").strip()
                if not ticket:
                    continue
                workflow = task_workflow_manager.get_by_ticket(ticket)
                if workflow and workflow.status in {"active", "verifying", "waiting_job", "ready_to_report"}:
                    primary_ticket = ticket
                    break
        except Exception:
            pass
        if not primary_ticket:
            for msg in reversed(batch):
                if msg.reply_ticket_id:
                    primary_ticket = msg.reply_ticket_id
                    break''',
'''        # Pick primary reply_ticket: the most recent input carrying one.
        primary_ticket = ""
        for msg in reversed(batch):
            if msg.reply_ticket_id:
                primary_ticket = msg.reply_ticket_id
                break''')

# 7. terminal callback finished-workflow skip
rep('''    def _process_terminal_input(self, input_msg: InputMessage, agent: Agent):
        if input_msg.reply_ticket_id:
            _wf = task_workflow_manager.get_by_ticket(input_msg.reply_ticket_id)
            if _wf and _wf.status in {"completed", "cancelled", "failed"}:
                logger.info(
                    "[AgentSession] Skipping callback for finished workflow: "
                    "item=%s ticket=%s status=%s",
                    self.item_id, input_msg.reply_ticket_id, _wf.status,
                )
                return
        internal_task_continuation = (''',
'''    def _process_terminal_input(self, input_msg: InputMessage, agent: Agent):
        internal_task_continuation = (''')

# 8. find_resumable matched_entry
rep('''            matched_entry = None
            if not internal_task_continuation:
                resumable = task_workflow_manager.find_resumable(
                    item_id=self.item_id,
                    source_type="",
                    source_label="",
                )
                if (
                    resumable
                    and resumable.reply_ticket_id
                    and resumable.status in {"waiting_job", "blocked"}
                ):
                    matched_entry = {"id": resumable.reply_ticket_id}
            if matched_entry:
                input_msg.reply_ticket_id = str(matched_entry["id"])
                self._attach_reply_ticket_to_agent(agent, input_msg.reply_ticket_id)
            elif not input_msg.reply_ticket_id:''',
'''            if not input_msg.reply_ticket_id:''')

# 9. reset_auto_resume
rep('''        if not internal_task_continuation and input_msg.reply_ticket_id:
            task_workflow_manager.reset_auto_resume(input_msg.reply_ticket_id)

''')

# 10. finalization gate
rep('''                finalization_only = False
                if iteration_index == MAX_ITERATIONS - 1:
                    can_finalize, _ = task_workflow_manager.can_finalize(
                        input_msg.reply_ticket_id
                    )
                    if can_finalize:
                        finalization_only = True
                        messages.append(
                            {
                                "role": "system",
                                "content": (
                                    "The tool-call budget is finished. Do not call any more "
                                    "tools. Use the latest confirmed tool results to give the "
                                    "user one concise final answer now."
                                ),
                            }
                        )
                    else:
                        messages.append(
                            {
                                "role": "system",
                                "content": (
                                    "This is the action-recovery pass for an unfinished task. "
                                    "Do not answer with a diagnosis, recommendation, promise, or "
                                    "next-step sentence. Call exactly one concrete execution tool "
                                    "that advances the current workflow. If the previous method "
                                    "failed, execute a safe recovery action now."
                                ),
                            }
                        )''',
'''                finalization_only = False
                if iteration_index == MAX_ITERATIONS - 1:
                    finalization_only = True
                    messages.append(
                        {
                            "role": "system",
                            "content": (
                                "The tool-call budget is finished. Do not call any more "
                                "tools. Use the latest confirmed tool results to give the "
                                "user one concise final answer now."
                            ),
                        }
                    )''')

# 11. workflow correction on final content
rep('''                        can_finalize, workflow_correction = (
                            task_workflow_manager.can_finalize(
                                input_msg.reply_ticket_id
                            )
                        )
                        if not can_finalize:
                            messages.append(
                                {"role": "assistant", "content": final_content}
                            )
                            messages.append(
                                {"role": "system", "content": workflow_correction}
                            )
                            self._emit_running_terminal_status(
                                analysis.terminal_source
                            )
                            continue
                        reply_ticket = self._get_reply_ticket(''',
'''                        reply_ticket = self._get_reply_ticket(''')

# 12. latest_progress emit
rep('''                        workflow = task_workflow_manager.get_by_ticket(
                            input_msg.reply_ticket_id
                        )
                        if workflow and workflow.latest_progress:
                            self.emit_output(
                                workflow.latest_progress,
                                "agent_response",
                            )
                    break''',
'''                    break''')

# 13. else branch failure report
rep('''            else:
                has_running_jobs = task_workflow_manager.has_running_jobs(
                    input_msg.reply_ticket_id
                )
                if not has_running_jobs:
                    can_finalize, _ = task_workflow_manager.can_finalize(
                        input_msg.reply_ticket_id
                    )
                    if not can_finalize:
                        terminal_failure_report = (
                            "任务未能完成：本轮未启动后台任务且无法继续推进，已停止。重新发送指令可继续。"
                        )

            if terminal_failure_report:''',
'''            if terminal_failure_report:''')

# 14. _wf_done delivery elif
rep('''            elif input_msg.reply_ticket_id and not _response_emitted_in_loop:
                _wf_done = task_workflow_manager.get_by_ticket(
                    input_msg.reply_ticket_id
                )
                if (
                    _wf_done
                    and _wf_done.status in {"ready_to_report", "completed", "cancelled"}
                    and _wf_done.latest_progress
                ):
                    _post_ticket = self._get_reply_ticket(
                        input_msg.reply_ticket_id
                    )
                    if _post_ticket and _post_ticket.source_type == "qq":
                        self._deliver_terminal_reply_ticket(
                            input_msg.reply_ticket_id,
                            _wf_done.latest_progress,
                        )
                    else:
                        self.emit_output(
                            _wf_done.latest_progress,
                            "agent_response",
                        )
''')

# 15. record_tool_call
rep('''            if tool_name != "mcp_local_update_task_workflow":
                task_workflow_manager.record_tool_call(
                    reply_ticket_id,
                    tool_name=tool_name,
                    command=str(tool_args.get("command") or ""),
                )

''')

# 16. ready_to_report force-complete
rep('''            # Once the agent attempts a report send while the workflow is
            # ready_to_report, force-complete the workflow regardless of
            # send success/failure. The report is a notification, not a
            # gate -- this prevents infinite retry loops on send errors.
            if (
                tool_name == ROBOT_SEND_TOOL_NAME
                and reply_ticket_id
                and not robot_delivery_result
            ):
                _wf = task_workflow_manager.get_by_ticket(reply_ticket_id)
                if _wf and _wf.status == "ready_to_report":
                    task_workflow_manager.on_delivery(reply_ticket_id)
                    robot_delivery_result = True
            delivery_is_final = True
            if robot_delivery_result:
                delivery_is_final, _ = task_workflow_manager.can_finalize(
                    reply_ticket_id
                )
            if (''',
'''            if (''')

# 17. fallback on_delivery
rep('''                    logger.exception(
                        "[AgentSession] Failed to mark QQ reply delivered: item=%s ticket=%s",
                        self.item_id,
                        reply_ticket_id,
                    )
                    # Fallback: force-complete workflow directly if
                    # mark_delivered failed, to prevent report loops.
                    try:
                        task_workflow_manager.on_delivery(reply_ticket_id)
                    except Exception:
                        pass
''',
'''                    logger.exception(
                        "[AgentSession] Failed to mark QQ reply delivered: item=%s ticket=%s",
                        self.item_id,
                        reply_ticket_id,
                    )
''')

# 18. _wf_after stop-turn check
rep('''                # Report sent and workflow completed -- stop the turn
                # immediately to prevent duplicate reports.
                _wf_after = task_workflow_manager.get_by_ticket(reply_ticket_id)
                if not _wf_after or _wf_after.status in {"completed", "cancelled", "failed"}:
                    return None''',
'''                # Report sent -- stop the turn immediately to prevent
                # duplicate reports.
                return None''')

# 19. mark_job_started
rep('''            if is_background_job_started_result(result):
                task_workflow_manager.mark_job_started(
                    reply_ticket_id,
                    command=str(tool_args.get("command") or ""),
                )
                clear_pending_terminal_continuation(''',
'''            if is_background_job_started_result(result):
                clear_pending_terminal_continuation(''')

# 20. record_tool_result
rep('''            if tool_name != "mcp_local_update_task_workflow":
                task_workflow_manager.record_tool_result(
                    reply_ticket_id,
                    tool_name=tool_name,
                    success=bool(result.get("success", True))
                    and not result_text.lower().startswith("error:"),
                    result_summary=result_text,
                )

''')

# 21. abort workflow cancel
rep("            self._cancel_active_workflows_on_abort()\n")
i = src.find("    def _cancel_active_workflows_on_abort(self):")
assert i >= 0
j = src.find("\n    def ", i + 10)
if j < 0:
    j = len(src)
src = src[:i] + src[j+1:]

remaining = [l for l in src.splitlines() if "task_workflow" in l]
print("REMAINING:", len(remaining))
for l in remaining[:10]:
    print("  ", l.strip()[:110])
path.write_text(src, encoding="utf-8")
print("session.py patched")
