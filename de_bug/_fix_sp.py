filepath = r"E:\dev\TermMan\dev\TermMan\backend\skills\system\SYSTEM_PROMPT.md"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

# Add workflow section before 安装清单
old = '''    ## 安装清单'''
new = '''    ## 任务工作流
    - 收到 3 步以上的任务（安装/卸载/配置/编译+验证），必须先调 update_task_workflow(action=create) 建 workflow 再执行。
    - 每完成一步调 complete_current_step，失败调 insert_recovery_step。
    - 任务完成或失败都要汇报给来源通道。

    ## 安装清单'''

if old in content:
    content = content.replace(old, new, 1)
    with open(filepath, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    print("PATCHED: workflow section added to system prompt")
else:
    print("NOT FOUND")
    print(content[:500])