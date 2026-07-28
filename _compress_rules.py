path = '/app/backend/app/services/agent/task_workflow.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Find and replace the 17 rules with compressed 8 rules
old_rules_start = '''            [
                "\u4e0d\u53ef\u8fdd\u53cd\u7684\u5de5\u4f5c\u6d41\u89c4\u5219\uff1a",'''

# Find the rules block - from the opening bracket to the closing ]
import re
rules_pattern = r'(            \[\n                "\u4e0d\u53ef\u8fdd\u53cd\u7684\u5de5\u4f5c\u6d41\u89c4\u5219\uff1a",.*?\n            \])'
match = re.search(rules_pattern, content, re.DOTALL)
if not match:
    print("ERROR: rules block not found")
    import sys; sys.exit(1)

old_rules = match.group(1)
print(f"Found rules block: {len(old_rules)} chars")

new_rules = '''            [
                "\u5de5\u4f5c\u6d41\u89c4\u5219\uff1a",
                "1. main_objective \u4e0d\u53ef\u6539\u5199\u3002\u5b50\u6b65\u9aa4\u5931\u8d25\u2192cancelled\u2192insert_recovery_step\u2192\u7ee7\u7eed\u3002\u4e0d\u884d\u751f\u65b0 workflow\u3002",
                "2. \u89c2\u5bdf\u5230\u8bc1\u636e\u540e\u7acb\u5373\u8c03 update_task_workflow \u8bb0\u5f55\u3002\u4e0d\u4f9d\u8d56\u8bb0\u5fc6\u63a8\u8fdb\u3002",
                "3. \u6c47\u62a5\u53ea\u5728\u5b8c\u6210/\u6700\u7ec8\u5931\u8d25/\u91cd\u5927\u53d8\u66f4\u65f6\u53d1\u3002\u4e2d\u95f4\u6b65\u9aa4\u4fdd\u6301\u9759\u9ed8\u3002\u6bcf\u6b21\u4e00\u6761\u7b80\u6d01\u6d88\u606f\u3002",
                "4. \u9884\u8ba1>3\u6b65\u7684\u4efb\u52a1\u5fc5\u987b\u5efa workflow\u3002\u666e\u901a\u804a\u5929\u548c\u5373\u65f6\u64cd\u4f5c\u4e0d\u9700\u8981\u3002",
                "5. \u68c0\u67e5\u6b65\u9aa4\u53d1\u73b0\u76ee\u6807\u5df2\u6ee1\u8db3\u2192\u53d6\u6d88\u5269\u4f59\u6b65\u9aa4\u2192\u76f4\u63a5\u6c47\u62a5\u3002\u4e0d\u9010\u6b65\u8d70\u3002",
                "6. \u53ef\u6062\u590d\u51b3\u7b56\uff08\u6362\u6e90/\u91cd\u8bd5/\u6362\u5305\uff09\u76f4\u63a5\u505a\uff0c\u4e0d\u95ee\u7528\u6237\u3002\u6240\u6709\u65b9\u6848\u8017\u5c3d\u624d\u62a5\u544a\u5931\u8d25\u3002",
                "7. \u7528\u6237\u65b0\u6307\u4ee4\u4e0e\u5f53\u524d workflow \u76ee\u6807\u4e0d\u540c\u2192\u7acb\u5373 cancel \u65e7\u7684\u2192\u6309\u65b0\u6307\u4ee4\u884c\u4e8b\u3002",
                "8. \u95f2\u804a/\u95ee\u5019/\u5373\u65f6\u67e5\u8be2\u76f4\u63a5\u56de\u7b54\uff0c\u4e0d\u8c03 update_task_workflow\u3002",
            ]'''

content = content.replace(old_rules, new_rules)
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

old_chars = len(old_rules)
new_chars = len(new_rules)
print(f"OK: compressed rules from {old_chars} to {new_chars} chars (saved {old_chars - new_chars}, ~{(old_chars - new_chars)//2} tokens)")
