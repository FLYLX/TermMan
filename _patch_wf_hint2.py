path = '/app/backend/app/services/agent/mcp/local_server.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Add _workflow_step_hint helper right before _format_background_job_robot_message
anchor = '    def _format_background_job_robot_message(self, command: str, result: dict, *, reply_ticket_id: str = "", workflow_id: str = "") -> str:'
helper = '''    def _workflow_step_hint(self, reply_ticket_id: str, workflow_id: str) -> str:
        try:
            from app.services.agent.task_workflow import task_workflow_manager
            wf = (
                task_workflow_manager._workflows.get(workflow_id)
                if workflow_id
                else None
            ) or task_workflow_manager.get_by_ticket(reply_ticket_id)
            if not wf:
                return ""
            step = wf.current_step()
            if not step:
                return ""
            idx = wf.current_step_index + 1
            total = len(wf.steps)
            return f"\u5f53\u524d\u6b65\u9aa4: {idx}/{total} [{step.title}]\u3002"
        except Exception:
            return ""

'''

if anchor in content:
    content = content.replace(anchor, helper + anchor)
    print("OK: added _workflow_step_hint")
else:
    print("ERROR: anchor not found")
    import sys; sys.exit(1)

# Now update _format_background_job_feedback to also include step hint
old_feedback = '''    def _format_background_job_feedback(self, result: dict, *, reply_ticket_id: str = "", workflow_id: str = "") -> str:
        has_workflow = bool(workflow_id)
        if result.get("success"):
            if has_workflow:
                header = (
                    "[Background terminal job completed]\\n"
                    "\u540e\u53f0\u4efb\u52a1\u5df2\u5b8c\u6210\u3002\u4f60\u5fc5\u987b\u7acb\u5373\u8c03\u7528 mcp_local_update_task_workflow "
                    "(action=complete_current_step \u6216 insert_recovery_step) \u63a8\u8fdb\u5de5\u4f5c\u6d41\u3002"
                    "\u4e0d\u8981\u53ea\u63cf\u8ff0\u7ed3\u679c\u800c\u4e0d\u64cd\u4f5c\u3002"
                )
            else:
                header = (
                    "[Background terminal job completed]\\n"
                    "\u540e\u53f0\u4efb\u52a1\u5df2\u5b8c\u6210\u3002\u6839\u636e\u7ed3\u679c\u76f4\u63a5\u56de\u590d\u7528\u6237\u3002"
                    "\u5982\u679c\u6b64\u547d\u4ee4\u7684\u7ed3\u679c\u5df2\u5728\u4e4b\u524d\u7684\u56de\u590d\u4e2d\u5904\u7406\u8fc7\uff0c\u9759\u9ed8\u7ed3\u675f\u5373\u53ef\uff0c\u4e0d\u8981\u91cd\u590d\u56de\u590d\u3002"
                )
            return f"{header}\\n{self._format_job_result(result)}"
        return (
            "[Background terminal job failed]\\n"
            "\u540e\u53f0\u4efb\u52a1\u8bf7\u6c42\u5931\u8d25\uff0c\u8bf7\u6839\u636e\u9519\u8bef\u4fe1\u606f\u51b3\u5b9a\u662f\u5426\u91cd\u8bd5\u6216\u6362\u65b9\u6848\u3002\\n"
            f"Error: {result.get('error', 'daemon job failed')}\\n"
            f"command: {result.get('command', '')}"
        )'''

new_feedback = '''    def _format_background_job_feedback(self, result: dict, *, reply_ticket_id: str = "", workflow_id: str = "") -> str:
        has_workflow = bool(workflow_id)
        if result.get("success"):
            if has_workflow:
                step_hint = self._workflow_step_hint(reply_ticket_id, workflow_id)
                header = (
                    "[Background terminal job completed]\\n"
                    "\u540e\u53f0\u4efb\u52a1\u5df2\u5b8c\u6210\u3002"
                    + step_hint
                    + "\u4f60\u7684\u7b2c\u4e00\u4e2a\u52a8\u4f5c\u5fc5\u987b\u662f\u8c03\u7528 mcp_local_update_task_workflow "
                    "(action=complete_current_step \u6216 insert_recovery_step)\uff0c"
                    "\u7528\u4e0b\u9762\u7684\u8f93\u51fa\u4f5c\u4e3a evidence\u3002"
                    "\u4e0d\u8981\u5148\u8c03 read_terminal_log \u6216 list_jobs\u3002"
                )
            else:
                header = (
                    "[Background terminal job completed]\\n"
                    "\u540e\u53f0\u4efb\u52a1\u5df2\u5b8c\u6210\u3002\u6839\u636e\u7ed3\u679c\u76f4\u63a5\u56de\u590d\u7528\u6237\u3002"
                    "\u5982\u679c\u6b64\u547d\u4ee4\u7684\u7ed3\u679c\u5df2\u5728\u4e4b\u524d\u7684\u56de\u590d\u4e2d\u5904\u7406\u8fc7\uff0c\u9759\u9ed8\u7ed3\u675f\u5373\u53ef\uff0c\u4e0d\u8981\u91cd\u590d\u56de\u590d\u3002"
                )
            return f"{header}\\n{self._format_job_result(result)}"
        step_hint = self._workflow_step_hint(reply_ticket_id, workflow_id) if has_workflow else ""
        return (
            "[Background terminal job failed]\\n"
            + step_hint
            + "\u540e\u53f0\u4efb\u52a1\u5931\u8d25\u3002\u8c03\u7528 mcp_local_update_task_workflow "
            "(action=insert_recovery_step) \u6362\u65b9\u6cd5\u7ee7\u7eed\uff0c\u6216\u786e\u8ba4\u65e0\u66f4\u591a\u65b9\u6cd5\u65f6\u6c47\u62a5\u5931\u8d25\u3002\\n"
            f"Error: {result.get('error', 'daemon job failed')}\\n"
            f"command: {result.get('command', '')}"
        )'''

if old_feedback in content:
    content = content.replace(old_feedback, new_feedback)
    print("OK: replaced _format_background_job_feedback")
else:
    print("ERROR: could not find _format_background_job_feedback")
    import sys; sys.exit(1)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("DONE")
