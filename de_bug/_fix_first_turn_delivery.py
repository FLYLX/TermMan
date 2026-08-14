# -*- coding: utf-8 -*-
import io, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
p = r"E:\dev\TermPaws\dev\TermPaws\backend\app\plugins\robot\prompts.py"
s = open(p, encoding="utf-8").read()

old1 = "ROBOT_DELIVERY_CONTRACT_INSTRUCTION = (\n    \"- \u53d1\u9001\u7eaa\u5f8b\uff1a"
new1 = "ROBOT_DELIVERY_CONTRACT_INSTRUCTION = (\n    \"- \u56de\u590d\u5f53\u8f6e\u53d1\u51fa\uff1a\u5224\u65ad\u9700\u8981\u56de\u590d QQ \u65f6\uff0c\u5fc5\u987b\u5728\u5f53\u524d\u54cd\u5e94\u91cc\u76f4\u63a5\u8c03\u7528 `mcp_robot_send_message` \u628a\u56de\u590d\u53d1\u51fa\uff1b\u7981\u6b62\u53ea\u8f93\u51fa\u6700\u7ec8\u6587\u672c\u7b49\u7cfb\u7edf\u4ee3\u53d1\u3002\u5224\u65ad\u65e0\u9700\u56de\u590d\u65f6\u4e0d\u8c03\u53d1\u9001\u5de5\u5177\uff0c\u6700\u7ec8\u6587\u672c\u53ea\u8fd4\u56de `[no_qq_reply]`\u3002\\n- \u53d1\u9001\u7eaa\u5f8b\uff1a"

old2 = "\"\u9700\u8981\u5411 QQ \u53d1\u9001\u53ef\u89c1\u6d88\u606f\u65f6\uff0c\u8c03\u7528 `mcp_robot_send_message`\u3002\\n\""
new2 = "\"\u9700\u8981\u5411 QQ \u53d1\u9001\u53ef\u89c1\u6d88\u606f\u65f6\uff0c\u5728\u5f53\u524d\u54cd\u5e94\u91cc\u76f4\u63a5\u8c03\u7528 `mcp_robot_send_message` \u5b8c\u6210\u53d1\u9001\uff1b\u4e0d\u8981\u53ea\u8f93\u51fa\u6700\u7ec8\u6587\u672c\u7b49\u5f85\u4e0b\u4e00\u8f6e\u4ee3\u53d1\u3002\\n\""

old3 = "\"\u6700\u7ec8 assistant \u6587\u672c\u662f TermPaws \u5185\u90e8\u56de\u590d\uff0c\u4e0d\u4f1a\u81ea\u52a8\u53d1\u9001\u5230 QQ\u3002\\n\""
new3 = "\"\u6700\u7ec8 assistant \u6587\u672c\u662f TermPaws \u5185\u90e8\u56de\u590d\uff0c\u4e0d\u4f1a\u81ea\u52a8\u53d1\u9001\u5230 QQ\uff1b\u56de\u590d\u5185\u5bb9\u5fc5\u987b\u901a\u8fc7 `mcp_robot_send_message` \u53d1\u51fa\u3002\\n\""

for name, old, new in [("contract_bullet", old1, new1), ("send_line", old2, new2), ("internal_text_line", old3, new3)]:
    c = s.count(old)
    assert c == 1, f"{name}: anchor count={c}"
    s = s.replace(old, new)
    print(f"{name}: replaced OK")

open(p, "w", encoding="utf-8", newline="").write(s)
print("file written")
