path = '/app/backend/app/services/agent/task_workflow.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Add to rule 3 about reporting
old = '"3. \u6c47\u62a5\u53ea\u5728\u5b8c\u6210/\u6700\u7ec8\u5931\u8d25/\u91cd\u5927\u53d8\u66f4\u65f6\u53d1\u3002\u4e2d\u95f4\u6b65\u9aa4\u4fdd\u6301\u9759\u9ed8\u3002\u6bcf\u6b21\u4e00\u6761\u7b80\u6d01\u6d88\u606f\u3002",'
new = '"3. \u6c47\u62a5\u53ea\u5728\u5b8c\u6210/\u6700\u7ec8\u5931\u8d25/\u91cd\u5927\u53d8\u66f4\u65f6\u53d1\u3002\u4e2d\u95f4\u6b65\u9aa4\u4fdd\u6301\u9759\u9ed8\u3002\u6c47\u62a5\u53d1\u9001\u5931\u8d25\uff08\u5982 bridge 404\uff09\u4e0d\u7b49\u4e8e\u4efb\u52a1\u5931\u8d25\uff0c\u6b65\u9aa4\u5df2\u5b8c\u6210\u5c31\u6807 completed\uff0c\u5728 evidence \u6ce8\u660e\u6295\u9012\u5931\u8d25\u5373\u53ef\u3002",'

if old in content:
    content = content.replace(old, new)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("OK: report failure != task failure")
else:
    print("WARN: rule 3 not found")
