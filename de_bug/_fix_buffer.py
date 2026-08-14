import re

path = r"E:\dev\TermPaws\dev\TermPaws\backend\app\services\agent\mcp\local_server.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace the busy-buffer branch with always-immediate delivery
old = '''            if busy:
                # A turn is running: hold this result and let the turn-end
                # hook merge it with other finished jobs into one batch.
                buffer_background_job_result(item_id, entry)
                debug_log(
                    f"[LocalMCPServer] background job result buffered while turn is running: item={item_id}, command={command}"
                )
                return
            flush_background_job_results_for_entries(item_id, [entry])'''

new = '''            # Always deliver immediately – the session input queue is
            # serialised by the turn coordinator, so enqueueing while a
            # turn is running is safe and avoids stalled workflows when
            # the turn ends without the agent acting on the result.
            flush_background_job_results_for_entries(item_id, [entry])'''

count = content.count(old)
print(f"Found {count} occurrences")
if count > 0:
    content = content.replace(old, new, 1)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(content)
    # Verify
    with open(path, "r", encoding="utf-8") as f:
        v = f.read()
    if "Always deliver immediately" in v:
        print("[OK] Job result buffering removed - always immediate delivery")
    else:
        print("[FAIL] Fix not found after write")
else:
    print("[SKIP] Pattern not found")