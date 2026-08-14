import re, pathlib, sys

root = pathlib.Path(r"E:\dev\TermPaws\dev\TermPaws")

def edit(rel, pairs, must_all=True):
    p = root / rel
    text = p.read_text(encoding="utf-8")
    missing = []
    for old, new in pairs:
        if old not in text:
            missing.append(old.splitlines()[0][:80])
            continue
        if text.count(old) > 1:
            print(f"!! MULTIPLE matches in {rel}: {old.splitlines()[0][:80]}")
            sys.exit(1)
        text = text.replace(old, new)
    if missing and must_all:
        print(f"!! MISSING in {rel}:")
        for m in missing: print("   ", m)
        sys.exit(1)
    p.write_text(text, encoding="utf-8")
    print(f"ok: {rel}")

# ---------------- session.py ----------------
edit(r"backend\app\services\agent\session.py", [
    ('    SCHEDULED_TASK = "scheduled_task"\n    TASK_CONTINUATION = "task_continuation"\n',
     '    SCHEDULED_TASK = "scheduled_task"\n'),
    ('            InputType.TASK_CONTINUATION: "\u4efb\u52a1\u7eed\u8dd1",\n', ''),
    ('        if input_msg.input_type in {InputType.TERMINAL, InputType.TASK_CONTINUATION}:\n',
     '        if input_msg.input_type == InputType.TERMINAL:\n'),
    ('    def _process_terminal_input(self, input_msg: InputMessage, agent: Agent):\n'
     '        internal_task_continuation = (\n'
     '            input_msg.input_type == InputType.TASK_CONTINUATION\n'
     '        )\n'
     '        combined_input = "\\n".join(\n',
     '    def _process_terminal_input(self, input_msg: InputMessage, agent: Agent):\n'
     '        combined_input = "\\n".join(\n'),
    ('        analysis = (\n'
     '            TerminalAnalysisResult(\n'
     '                content=input_msg.content,\n'
     '                terminal_source=TERMINAL_SOURCE_FILTERED,\n'
     '            )\n'
     '            if internal_task_continuation\n'
     '            else self._resolve_terminal_analysis_content(input_msg)\n'
     '        )\n'
     '        if input_msg.content and not internal_task_continuation:\n',
     '        analysis = self._resolve_terminal_analysis_content(input_msg)\n'
     '        if input_msg.content:\n'),
    ('        should_emit_terminal_output = bool(input_msg.content) and not internal_task_continuation and (\n',
     '        should_emit_terminal_output = bool(input_msg.content) and (\n'),
])

# ---------------- state_store.py ----------------
p = root / r"backend\app\services\agent\state_store.py"
text = p.read_text(encoding="utf-8")

old_cls = '''class WorkflowStateRow(_StateBase):
    __tablename__ = "agent_workflow_state"

    workflow_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    item_id: Mapped[str] = mapped_column(String(64), index=True, default="")
    status: Mapped[str] = mapped_column(String(32), index=True, default="")
    updated_at: Mapped[str] = mapped_column(String(64), index=True, default="")
    payload: Mapped[str] = mapped_column(Text, default="{}")


class TicketStateRow(_StateBase):'''
assert text.count(old_cls) == 1
text = text.replace(old_cls, 'class TicketStateRow(_StateBase):')

# drop whole "Workflow rows" section up to next section header
pattern = re.compile(
    r"# -{75}\n# Workflow rows\n# -{75}\n.*?        session\.close\(\)\n\n\n(?=# -{75}\n)",
    re.DOTALL,
)
new_text, n = pattern.subn("", text)
assert n == 1, f"workflow section sub matched {n} times"
text = new_text

old_clear = '''            for model in (
                WorkflowStateRow,
                TicketStateRow,
                KVStateRow,
            ):'''
assert text.count(old_clear) == 1
text = text.replace(old_clear, '''            for model in (
                TicketStateRow,
                KVStateRow,
            ):''')

for name in ('"delete_workflow",\n', '"load_workflows",\n', '"save_workflow",\n'):
    assert text.count(name) == 1, name
    text = text.replace(name, "")

p.write_text(text, encoding="utf-8")
print("ok: state_store.py")

# ---------------- delete workflow app files ----------------
for rel in (r"backend\app\api\routes\task_workflows.py",
            r"backend\app\services\agent\task_workflow.py"):
    fp = root / rel
    assert fp.exists(), rel
    fp.unlink()
    print("deleted:", rel)

print("STAGE1 DONE")
