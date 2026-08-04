# -*- coding: utf-8 -*-
from pathlib import Path
path = Path(r"backend\app\services\agent\session.py")
src = path.read_text(encoding="utf-8")
old = '''        self._cancel_pending_command_recheck()
        if clear_queue:
        self.emit_status("interrupting", "中断当前轮中")'''
new = '''        self._cancel_pending_command_recheck()
        self.emit_status("interrupting", "中断当前轮中")'''
assert src.count(old) == 1
path.write_text(src.replace(old, new), encoding="utf-8")
print("fixed")
