# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
p = r"E:\dev\TermPaws\dev\TermPaws\backend\app\services\agent\mcp\local_server.py"
s = open(p, encoding="utf-8").read()

# 1) no-plan branch: stop ordering a reply; let the agent decide
old_else = '''            instruction = (
                "\u6839\u636e\u7ed3\u679c\u76f4\u63a5\u56de\u590d\u7528\u6237\u3002"
                "\u5982\u679c\u7528\u6237\u539f\u59cb\u8bf7\u6c42\u8868\u793a\u4e0d\u9700\u8981\u56de\u590d\uff0c\u6700\u7ec8\u53ea\u8f93\u51fa NRN \u5373\u53ef\u3002"
            )'''
new_else = '''            instruction = ""'''

# 2) return block: tolerate empty instruction
old_ret = '''        return (
            "[\u540e\u53f0\u7ec8\u7aef\u4efb\u52a1\u7ed3\u679c - \u6765\u81ea QQ \u4f1a\u8bdd]\\n"
            f"\u540e\u53f0\u4efb\u52a1\u5df2{status}\u3002\\n"
            f"{instruction}\\n"
            f"{request_boundary}"
            f"\u547d\u4ee4: {command}\\n"
            f"{self._format_job_result(result)}"
        )'''
new_ret = '''        instruction_line = f"{instruction}\\n" if instruction else ""
        return (
            "[\u540e\u53f0\u7ec8\u7aef\u4efb\u52a1\u7ed3\u679c - \u6765\u81ea QQ \u4f1a\u8bdd]\\n"
            f"\u540e\u53f0\u4efb\u52a1\u5df2{status}\u3002\\n"
            f"{instruction_line}"
            f"{request_boundary}"
            f"\u547d\u4ee4: {command}\\n"
            f"{self._format_job_result(result)}"
        )'''

# 3) helper: pure context, no instructions
old_helper = '''    def _job_callback_task_boundary(self, reply_ticket_id: str) -> str:
        """Task boundary for job callbacks: pin the turn to the ticket's own
        original request so stale tasks in memory/history/live context cannot
        hijack the callback turn, and carry the original reply requirement
        (e.g. explicit no-reply) into the callback."""
        if not reply_ticket_id:
            return ""
        try:
            from app.services.agent.reply_ticket import reply_ticket_manager

            ticket = reply_ticket_manager.get(reply_ticket_id)
            request = str(getattr(ticket, "request_message", "") or "").strip() if ticket else ""
            if not request:
                return ""
            if len(request) > 200:
                request = request[:200] + "\u2026"
            return (
                f"\u4efb\u52a1\u8fb9\u754c\uff1a\u672c\u6b21\u540e\u53f0\u4efb\u52a1\u6e90\u81ea\u7528\u6237\u8bf7\u6c42\uff1a\u300c{request}\u300d"
                "\u672c\u8f6e\u53ea\u5904\u7406\u8be5\u8bf7\u6c42\u7684\u540e\u7eed\uff1b\u8bb0\u5fc6\u3001\u5386\u53f2\u6216 live context \u91cc\u51fa\u73b0\u7684\u5176\u4ed6\u4efb\u52a1\u4e0e\u672c\u8f6e\u65e0\u5173\uff0c"
                "\u4e0d\u8981\u6062\u590d\u6216\u91cd\u65b0\u6267\u884c\u5b83\u4eec\u3002"
                "\u662f\u5426\u56de\u590d\u7528\u6237\u4ee5\u539f\u59cb\u8bf7\u6c42\u4e3a\u51c6\uff1a\u539f\u59cb\u8bf7\u6c42\u660e\u786e\u4e0d\u9700\u8981\u56de\u590d\u65f6\uff0c\u6700\u7ec8\u53ea\u8f93\u51fa NRN\u3002\\n"
            )
        except Exception:
            return ""

'''
new_helper = '''    def _job_callback_task_boundary(self, reply_ticket_id: str) -> str:
        """Task background for job callbacks: surface the ticket's original
        user request as pure context so the agent itself can judge scope and
        whether a reply is wanted (e.g. an explicit no-reply). No behavioral
        instructions -- the agent decides."""
        if not reply_ticket_id:
            return ""
        try:
            from app.services.agent.reply_ticket import reply_ticket_manager

            ticket = reply_ticket_manager.get(reply_ticket_id)
            request = str(getattr(ticket, "request_message", "") or "").strip() if ticket else ""
            if not request:
                return ""
            if len(request) > 200:
                request = request[:200] + "\u2026"
            return f"\u4efb\u52a1\u80cc\u666f\uff1a\u672c\u6b21\u540e\u53f0\u4efb\u52a1\u6e90\u81ea\u7528\u6237\u8bf7\u6c42\uff1a\u300c{request}\u300d\\n"
        except Exception:
            return ""

'''

for name, old, new in [("else_instr", old_else, new_else), ("return_block", old_ret, new_ret), ("helper", old_helper, new_helper)]:
    c = s.count(old)
    assert c == 1, f"{name}: anchor count={c}"
    s = s.replace(old, new)
    print(f"{name}: OK")

open(p, "w", encoding="utf-8", newline="").write(s)
print("written")
