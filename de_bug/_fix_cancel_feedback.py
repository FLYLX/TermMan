# -*- coding: utf-8 -*-

def load(path):
    with open(path, encoding="utf-8", newline="") as f:
        raw = f.read()
    had_crlf = "\r\n" in raw
    return raw.replace("\r\n", "\n"), had_crlf

def save(path, text, had_crlf):
    if had_crlf:
        text = text.replace("\n", "\r\n")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)

def replace_once(text, old, new, label):
    n = text.count(old)
    assert n == 1, "%s: expected 1 occurrence, found %d" % (label, n)
    return text.replace(old, new)

p = r"backend\app\services\agent\mcp\local_server.py"
t, crlf = load(p)

old = """    def _format_background_job_feedback(self, result: dict, *, reply_ticket_id: str = "") -> str:
        has_plan = bool(self._plan_reminder("", reply_ticket_id))
        if result.get("success"):"""
new = """    def _format_background_job_feedback(self, result: dict, *, reply_ticket_id: str = "") -> str:
        if result.get("cancelled"):
            return (
                "[Background terminal job cancelled]\\n"
                "\u540e\u53f0\u4efb\u52a1\u5df2\u88ab\u53d6\u6d88\uff08\u8fd9\u662f\u4e3b\u52a8\u53d6\u6d88\uff0c\u4e0d\u662f\u5931\u8d25\uff09\u3002\\n"
                "\u4e0d\u8981\u91cd\u8bd5\u8fd9\u4e2a\u4efb\u52a1\u3002\u8c03\u7528 mcp_local_update_plan "
                "\u628a\u5bf9\u5e94\u6b65\u9aa4\u6807\u8bb0\u4e3a cancelled\uff08\u6216\u5168\u90e8\u7ed3\u675f\u65f6\u7528 plan=[] \u6e05\u7a7a\uff09\uff0c"
                "\u7136\u540e\u7b80\u77ed\u786e\u8ba4\u4efb\u52a1\u5df2\u505c\u6b62\u5373\u53ef\u3002\\n"
                f"command: {result.get('command', '')}"
            )
        has_plan = bool(self._plan_reminder("", reply_ticket_id))
        if result.get("success"):"""
t = replace_once(t, old, new, "cancelled feedback branch")

old = """            if agent_session:
                agent_session.clear_terminal_job(command)
                agent_session.record_finished_job(
                    command,
                    job_id=str(result.get("job_id") or ""),
                    success=bool(result.get("success")),
                    exit_code=result.get("exit_code"),
                )"""
new = """            if agent_session:
                agent_session.clear_terminal_job(command)
                agent_session.record_finished_job(
                    command,
                    job_id=str(result.get("job_id") or ""),
                    success=bool(result.get("success")) and not result.get("cancelled"),
                    exit_code=result.get("exit_code"),
                )"""
t = replace_once(t, old, new, "finished job cancelled flag")
save(p, t, crlf)
print("local_server.py OK")
