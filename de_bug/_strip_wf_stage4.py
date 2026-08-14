import pathlib, re

root = pathlib.Path(r"E:\dev\TermPaws\dev\TermPaws")

# ---- SKILL.md ----
p = root / r"backend\skills\terminal_mcp\SKILL.md"
text = p.read_text(encoding="utf-8")
for ln in ("  - mcp_local_get_task_workflow\n", "  - mcp_local_update_task_workflow\n"):
    assert text.count(ln) == 1, ln
    text = text.replace(ln, "")
p.write_text(text, encoding="utf-8")
print("SKILL.md cleaned")

# ---- state_store.py docstring ----
p = root / r"backend\app\services\agent\state_store.py"
text = p.read_text(encoding="utf-8")
old = "Persists task workflows, reply tickets, and queued robot dispatch jobs so a"
assert text.count(old) == 1
text = text.replace(old, "Persists reply tickets and key-value agent state so a")
p.write_text(text, encoding="utf-8")
print("state_store.py docstring fixed")

# ---- MCP_TOOLS.md ----
p = root / r"docs\MCP_TOOLS.md"
text = p.read_text(encoding="utf-8")
section = """---

## 二、任务工作流（mcp_local_*）

### 8. get_task_workflow
- **用途**：查看当前任务工作流的状态（步骤、进度、job、阻塞原因）
- **参数**：无
- **场景**：需要了解任务执行到哪一步了

### 9. update_task_workflow
- **用途**：推进/更新任务工作流
- **参数**：`action`（必填）、`note`、`step_index`、`title`
- **action 取值**：
  - `record_progress` — 记录进展
  - `complete_current_step` — 完成当前步骤，推进到下一步
  - `insert_recovery_step` — 当前步骤失败时插入恢复步骤
  - `cancel` — 取消整个工作流
- **场景**：每完成一个步骤都要调这个推进状态机

"""
assert text.count(section) == 1, "section not found"
text = text.replace(section, "")
# renumber sections
for old_h, new_h in (("## 三、", "## 二、"), ("## 四、", "## 三、"), ("## 五、", "## 四、"),
                     ("## 六、", "## 五、"), ("## 七、", "## 六、")):
    assert text.count(old_h) == 1, old_h
    text = text.replace(old_h, new_h)
# renumber tool headings 10..30 -> 8..28
for n in range(10, 31):
    m = re.search(rf"^### {n}\. ", text, re.M)
    assert m, n
    text = text.replace(m.group(0), f"### {n-2}. ", 1)
row = "| 推进任务步骤 | `update_task_workflow` |\n"
assert text.count(row) == 1
text = text.replace(row, "")
p.write_text(text, encoding="utf-8")
print("MCP_TOOLS.md cleaned")
