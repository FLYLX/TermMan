import subprocess, pathlib

head = subprocess.check_output(
    ["git", "show", "HEAD:backend/app/services/agent/mcp/local_server.py"]
).decode("utf-8")
cur_path = pathlib.Path("backend/app/services/agent/mcp/local_server.py")
cur = cur_path.read_text(encoding="utf-8")

# 1) original block from HEAD: _start_background_job_thread signature through the immediate flush
sig = "    def _start_background_job_thread("
h_sig = head.index(sig)
flush_marker = "            flush_background_job_results_for_entries(item_id, [entry])\n"
h_flush = head.index(flush_marker, h_sig) + len(flush_marker)
orig_block = head[h_sig:h_flush]
assert "enqueue_job_result_flush" not in orig_block

# 2) current range: from _background_job_worker_body def through wrapper enqueue line
c_start = cur.index("    def _background_job_worker_body(")
end_marker = "                if entry is not None:\n                    enqueue_job_result_flush(item_id, entry, sibling_count=sibling_count)\n"
c_end = cur.index(end_marker) + len(end_marker)
cur = cur[:c_start] + orig_block + cur[c_end:]

# 3) remove coalescing helpers block
h_start_marker = "\n\n# Idle-time job result coalescing:"
h_start = cur.index(h_start_marker)
h_end_marker = "    flush_background_job_results_for_entries(item_id, entries)\n"
h_end = cur.index(h_end_marker, h_start) + len(h_end_marker)
removed = cur[h_start:h_end]
assert "_flush_coalesced_job_results" in removed and "enqueue_job_result_flush" in removed
cur = cur[:h_start] + cur[h_end:]

# 4) remove uuid import if now unused
assert "uuid.uuid4" not in cur, "uuid still used somewhere"
cur = cur.replace("import threading\nimport time\nimport uuid", "import threading\nimport time", 1)

assert "enqueue_job_result_flush" not in cur
assert "_background_job_worker_body" not in cur
assert "_active_background_jobs" not in cur
cur_path.write_text(cur, encoding="utf-8")
print("local_server.py coalescing reverted")