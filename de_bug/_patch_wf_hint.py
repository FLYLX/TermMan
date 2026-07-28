import re

path = '/app/backend/app/services/agent/mcp/local_server.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Replace _format_background_job_robot_message
old_robot = '''    def _format_background_job_robot_message(self, command: str, result: dict, *, reply_ticket_id: str = "", workflow_id: str = "") -> str:
        status = "\u5b8c\u6210" if result.get("success") else "\u5931\u8d25"
        has_workflow = bool(workflow_id)
        if has_workflow:
            instruction = (
                "\u91cd\u8981\uff1a\u4efb\u52a1\u5de5\u4f5c\u6d41\u6d3b\u8dc3\uff0c\u5fc5\u987b\u8c03\u7528 "
                "mcp_local_update_task_workflow (action=complete_current_step \u6216 "
                "insert_recovery_step) \u63a8\u8fdb\u5de5\u4f5c\u6d41\u3002"
                "\u4e0d\u8981\u4e3a\u4e2d\u95f4\u7ed3\u679c\u53d1\u9001 QQ \u6d88\u606f\u3002"
                "\u53ea\u5728\u5230\u8fbe\u6c47\u62a5\u6b65\u9aa4\u3001\u6700\u7ec8\u5931\u8d25\u4e14\u65e0\u66f4\u591a\u65b9\u6cd5\u3001\u6216\u91cd\u5927\u65b9\u5411\u53d8\u66f4\u65f6\u624d\u53d1 QQ\u3002"
                "\u9759\u9ed8\u5904\u7406\u6b64\u7ed3\u679c\u5e76\u7ee7\u7eed\u6267\u884c\u3002"
            )
        else:
            instruction = "\u6839\u636e\u7ed3\u679c\u76f4\u63a5\u56de\u590d\u7528\u6237\u3002"
        return (
            "[\u540e\u53f0\u7ec8\u7aef\u4efb\u52a1\u7ed3\u679c - \u6765\u81ea QQ \u4f1a\u8bdd]\\n"
            f"\u540e\u53f0\u4efb\u52a1\u5df2{status}\u3002\\n"
            f"{instruction}\\n"
            f"\u547d\u4ee4: {command}\\n"
            f"{self._format_job_result(result)}"
        )'''

new_robot = '''    def _format_background_job_robot_message(self, command: str, result: dict, *, reply_ticket_id: str = "", workflow_id: str = "") -> str:
        status = "\u5b8c\u6210" if result.get("success") else "\u5931\u8d25"
        has_workflow = bool(workflow_id)
        step_hint = ""
        if has_workflow:
            step_hint = self._workflow_step_hint(reply_ticket_id, workflow_id)
            instruction = (
                "\u91cd\u8981\uff1a\u4efb\u52a1\u5de5\u4f5c\u6d41\u6d3b\u8dc3\u3002"
                + step_hint
                + "\u4f60\u7684\u7b2c\u4e00\u4e2a\u52a8\u4f5c\u5fc5\u987b\u662f\u8c03\u7528 "
                "mcp_local_update_task_workflow (action=complete_current_step \u6216 "
                "insert_recovery_step)\uff0c\u7528\u4e0a\u9762\u7684\u8f93\u51fa\u4f5c\u4e3a evidence\u3002"
                "\u4e0d\u8981\u5148\u8c03 read_terminal_log \u6216 list_jobs\u3002"
                "\u4e0d\u8981\u4e3a\u4e2d\u95f4\u7ed3\u679c\u53d1\u9001 QQ \u6d88\u606f\u3002"
                "\u53ea\u5728\u5230\u8fbe\u6c47\u62a5\u6b65\u9aa4\u3001\u6700\u7ec8\u5931\u8d25\u4e14\u65e0\u66f4\u591a\u65b9\u6cd5\u3001\u6216\u91cd\u5927\u65b9\u5411\u53d8\u66f4\u65f6\u624d\u53d1 QQ\u3002"
            )
        else:
            instruction = "\u6839\u636e\u7ed3\u679c\u76f4\u63a5\u56de\u590d\u7528\u6237\u3002"
        return (
            "[\u540e\u53f0\u7ec8\u7aef\u4efb\u52a1\u7ed3\u679c - \u6765\u81ea QQ \u4f1a\u8bdd]\\n"
            f"\u540e\u53f0\u4efb\u52a1\u5df2{status}\u3002\\n"
            f"{instruction}\\n"
            f"\u547d\u4ee4: {command}\\n"
            f"{self._format_job_result(result)}"
        )'''

if old_robot in content:
    content = content.replace(old_robot, new_robot)
    print("OK: replaced _format_background_job_robot_message")
else:
    print("ERROR: could not find _format_background_job_robot_message")
    import sys; sys.exit(1)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("DONE")
