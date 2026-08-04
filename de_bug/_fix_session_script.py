from pathlib import Path
p = Path(r"de_bug\_strip_wf_session.py")
s = p.read_text(encoding="utf-8")
s = s.replace('''# 1. import
rep("from app.services.agent.task_workflow import task_workflow_manager\\n")''',
'''# 1. import (both occurrences)
import re as _re
src = _re.sub(r"^from app\\.services\\.agent\\.task_workflow import task_workflow_manager\\n", "", src, flags=_re.M)''')
p.write_text(s, encoding="utf-8")
print("script adjusted")
