# -*- coding: utf-8 -*-
import io

path = r"backend\app\services\agent\mcp\local_server.py"
src = io.open(path, encoding="utf-8").read()

old_robot = '''    def _format_background_job_robot_message(self, command: str, result: dict, *, reply_ticket_id: str = "") -> str:
        status = "\u5b8c\u6210" if result.get("success") else "\u5931\u8d25"
'''
new_robot = '''    def _format_background_job_robot_message(self, command: str, result: dict, *, reply_ticket_id: str = "") -> str:
        if result.get("cancelled"):
            return (
                "[\u540e\u53f0\u7ec8\u7aef\u4efb\u52a1\u7ed3\u679c - \u6765\u81ea QQ \u4f1a\u8bdd]\\n"
                "\u540e\u53f0\u4efb\u52a1\u5df2\u88ab\u4e3b\u52a8\u53d6\u6d88\uff08\u7528\u6237\u53d1\u8d77\u7684\u53d6\u6d88\uff0c\u4e0d\u662f\u5931\u8d25\uff09\u3002\\n"
                "\u4e0d\u8981\u91cd\u65b0\u6267\u884c\u8fd9\u4e2a\u4efb\u52a1\uff0c\u4e5f\u4e0d\u8981\u628a\u5b83\u5f53\u6210\u5931\u8d25\u3002"
                "\u5982\u679c plan \u91cc\u6709\u5bf9\u5e94\u6b65\u9aa4\uff0c\u8c03\u7528 mcp_local_update_plan \u628a\u5b83\u6807\u4e3a cancelled"
                "\uff08\u6216\u5168\u90e8\u7ed3\u675f\u65f6\u6e05\u7a7a plan\uff09\uff0c\u7136\u540e\u7b80\u77ed\u786e\u8ba4\u4efb\u52a1\u5df2\u505c\u6b62\u3002\\n"
                f"\u547d\u4ee4: {command}\\n"
            )
        status = "\u5b8c\u6210" if result.get("success") else "\u5931\u8d25"
'''
assert src.count(old_robot) == 1, f"robot anchor: {src.count(old_robot)}"
src = src.replace(old_robot, new_robot)

old_batch = '        status = "succeeded" if result.get("success") else "failed"'
new_batch = '''        if result.get("cancelled"):
            status = "cancelled (user-initiated cancel, NOT a failure; do not retry)"
        else:
            status = "succeeded" if result.get("success") else "failed"'''
assert src.count(old_batch) == 1, f"batch anchor: {src.count(old_batch)}"
src = src.replace(old_batch, new_batch)

io.open(path, "w", encoding="utf-8", newline="").write(src)
print("patched ok")
