path = '/app/backend/app/services/agent/task_workflow.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old = '\u6c47\u62a5\u53d1\u9001\u5931\u8d25\uff08\u5982 bridge 404\uff09\u4e0d\u7b49\u4e8e\u4efb\u52a1\u5931\u8d25\uff0c\u6b65\u9aa4\u5df2\u5b8c\u6210\u5c31\u6807 completed\uff0c\u5728 evidence \u6ce8\u660e\u6295\u9012\u5931\u8d25\u5373\u53ef\u3002'
new = '\u6c47\u62a5\u53d1\u9001\u5931\u8d25\uff08\u5982 bridge 404\uff09\u4e0d\u7b49\u4e8e\u4efb\u52a1\u5931\u8d25\uff0c\u76f4\u63a5\u5728 web chat \u8f93\u51fa\u7ed3\u679c\uff0c\u6807 completed\u3002'

if old in content:
    content = content.replace(old, new)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("OK: fallback to web chat")
else:
    print("WARN: not found")
