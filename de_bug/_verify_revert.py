import subprocess, pathlib
head = subprocess.check_output(["git", "show", "HEAD:backend/app/services/agent/mcp/local_server.py"]).decode("utf-8")
cur = pathlib.Path("backend/app/services/agent/mcp/local_server.py").read_text(encoding="utf-8")
sig = "    def _start_background_job_thread("
flush_marker = "            flush_background_job_results_for_entries(item_id, [entry])\n"
hb = head[head.index(sig): head.index(flush_marker) + len(flush_marker)]
cb = cur[cur.index(sig): cur.index(flush_marker) + len(flush_marker)]
print("worker block identical to HEAD:", hb == cb)
print("coalesce refs in cur:", cur.count("coalesce") + cur.count("_active_background_jobs"))
