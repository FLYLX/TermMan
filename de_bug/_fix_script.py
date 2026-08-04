from pathlib import Path
p = Path(r"de_bug\_strip_wf_chat.py")
s = p.read_text(encoding="utf-8")
s = s.replace('drop_block(r"^def _should_create_task_workflow\\(")\n', "")
s = s.replace('src = re.sub(r"^TASK_WORKFLOW_FINAL_ONLY_RE = .*\\n", "", src, flags=re.M)\n', "")
p.write_text(s, encoding="utf-8")
print("script fixed")
