# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
lines = open(r"backend/app/services/agent/mcp/local_server.py", encoding="utf-8").read().splitlines()
for start, end in [(1515, 1548), (1895, 1935), (2058, 2120)]:
    print(f"\n===== [{start}-{end}] =====")
    for i in range(start-1, min(end, len(lines))):
        print(f"{i+1:5}: {lines[i]}")
import re
src = "\n".join(lines)
for m in re.finditer(r"def _start_background_job_thread\(|def _poll_background_job_result\(|_attach_daemon_job_id_with_retry\(", src):
    ln = src[:m.start()].count("\n") + 1
    print("MARK", ln, lines[ln-1].strip()[:100])
