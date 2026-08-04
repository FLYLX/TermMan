# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
SVC = r"backend\app\plugins\robot\service.py"
src = open(SVC, encoding="utf-8").read()
old = '''        with self._lock:
            for _started, job in self._active_dispatch_jobs.items():
                queued_job = job[1]
                if (
                    str(queued_job.robot_id) == robot_id_text
                    and queued_job.conversation_key == conversation_key
                ):
                    return True
'''
new = '''        with self._lock:
            for _tracking_key, (_started, queued_job) in self._active_dispatch_jobs.items():
                if (
                    str(queued_job.robot_id) == robot_id_text
                    and queued_job.conversation_key == conversation_key
                ):
                    return True
'''
assert src.count(old) == 1, f"anchor count={src.count(old)}"
open(SVC, "w", encoding="utf-8", newline="\n").write(src.replace(old, new))
print("cleaned")
