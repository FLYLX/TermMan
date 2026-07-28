path = '/app/backend/app/services/agent/task_workflow.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Strengthen rule 6 slightly
old = '"6. \u53ef\u6062\u590d\u51b3\u7b56\uff08\u6362\u6e90/\u91cd\u8bd5/\u6362\u5305\uff09\u76f4\u63a5\u505a\uff0c\u4e0d\u95ee\u7528\u6237\u3002\u6240\u6709\u65b9\u6848\u8017\u5c3d\u624d\u62a5\u544a\u5931\u8d25\u3002",'
new = '"6. \u53ef\u6062\u590d\u51b3\u7b56\uff08\u6362\u6e90/\u91cd\u8bd5/\u6362\u5305\uff09\u76f4\u63a5\u505a\uff0c\u4e0d\u95ee\u7528\u6237\u3002\u540c\u4e00\u601d\u8def\u53cd\u590d\u5931\u8d25\u4e14\u60f3\u4e0d\u51fa\u65b0\u529e\u6cd5\u65f6\uff0c\u76f4\u63a5 cancel \u8be5\u6b65\u5e76\u628a\u5b9e\u9645\u9519\u8bef\u6c47\u62a5\u56de\u53bb\uff0c\u4e0d\u8981\u539f\u5730\u6253\u8f6c\u3002",'

if old in content:
    content = content.replace(old, new)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("OK: strengthened rule 6")
else:
    print("WARN: rule 6 not found exactly, skipping")
