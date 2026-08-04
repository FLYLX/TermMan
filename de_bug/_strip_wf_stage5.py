import pathlib

root = pathlib.Path(r"E:\dev\TermMan\dev\TermMan")
p = root / r"docs\全量对话测试.md"
text = p.read_text(encoding="utf-8")

old1 = """**检查命令**：
```bash
# 查 workflow 状态
docker exec -w /app/backend termman-backend-1 python -c "
from app.services.agent.task_workflow import task_workflow_manager
wfs = task_workflow_manager.list_active(item_id='ea52de0c-51b7-4b49-a43d-985ed2e09579')
for w in wfs: print(w.id, w.status, w.title)
"
```"""
new1 = """**检查命令**：
```bash
# 查回复 ticket 状态（workflow 子系统已移除，任务进度以 plan + ticket 跟踪）
docker exec -w /app/backend termman-backend-1 python -c "
from app.services.agent import state_store
for t in state_store.load_tickets():
    print(t.get('ticket_id'), t.get('status'))
"
```"""
assert text.count(old1) == 1
text = text.replace(old1, new1)

text = text.replace(
    "- [ ] Web：直接回复 \"2\"，不创建 workflow，不调 update_task_workflow",
    "- [ ] Web：直接回复 \"2\"，不启动后台任务",
)
text = text.replace(
    "- [ ] QQ：回复到 QQ（return_source = qq），不创建 workflow",
    "- [ ] QQ：回复到 QQ，不启动后台任务",
)
text = text.replace(
    "- [ ] 闲聊被直接回答（或告知正在忙），不调 update_task_workflow\n- [ ] workflow 的 return_targets 数量不增加\n",
    "- [ ] 闲聊被直接回答（或告知正在忙）\n",
)

old2 = """**检查方法**：
```bash
# 对比闲聊前后 workflow 的 return_targets 数量
docker exec -w /app/backend termman-backend-1 python -c "
from app.services.agent.task_workflow import task_workflow_manager
wfs = task_workflow_manager.list_active(item_id='ea52de0c-51b7-4b49-a43d-985ed2e09579')
for w in wfs:
    print(f'workflow={w.id[:12]} targets={len(w.return_targets)} steps={len(w.steps)}')
    for s in w.steps:
        print(f'  step {s.order}: {s.title} [{s.status}] attempts={s.attempts}')
"
```"""
new2 = """**检查方法**：
```bash
# 对比闲聊前后的 ticket 状态，确认原任务汇报目标不变
docker exec -w /app/backend termman-backend-1 python -c "
from app.services.agent import state_store
for t in state_store.load_tickets():
    print(t.get('ticket_id'), t.get('status'), t.get('item_id'))
"
```"""
assert text.count(old2) == 1
text = text.replace(old2, new2)

assert "task_workflow" not in text
p.write_text(text, encoding="utf-8")
print("全量对话测试.md cleaned")
