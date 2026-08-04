# -*- coding: utf-8 -*-
import sys, io, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
src = open(r"backend/app/services/agent/task_watchdog.py", encoding="utf-8").read()
lines = src.splitlines()
for i in range(498, min(575, len(lines))):
    print(f"{i+1:5}: {lines[i]}")
print()
for name in ["_closure_notice", "_get_daemon_connection_for_item", "_list_daemon_job_commands", "_item_has_live_execution", "_as_utc", "_stale_timeout_seconds", "CLOSE_REASON", "WAITING_JOB_CALLBACK_GRACE_SECONDS", "MAX_RECONCILE_ATTEMPTS"]:
    hits = [n+1 for n, l in enumerate(lines) if name in l]
    print(name, "->", hits)
