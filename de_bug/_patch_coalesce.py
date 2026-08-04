import pathlib

cfg_path = pathlib.Path("backend/app/core/config.py")
c = cfg_path.read_text(encoding="utf-8")
cfg_anchor = "    ROBOT_BACKEND_JOB_TIMEOUT_SECONDS: float = 240.0\n"
assert cfg_anchor in c, "config anchor not found"
assert "ROBOT_JOB_RESULT_COALESCE_WINDOW_SECONDS" not in c, "config already patched"
c = c.replace(cfg_anchor, cfg_anchor + "    ROBOT_JOB_RESULT_COALESCE_WINDOW_SECONDS: float = 20.0\n", 1)
cfg_path.write_text(c, encoding="utf-8")
print("config patched")

p = pathlib.Path("backend/app/services/agent/mcp/local_server.py")
src = p.read_text(encoding="utf-8")

assert "import uuid" not in src.split("\n")[:20], "uuid already imported?"
src = src.replace("import threading\nimport time", "import threading\nimport time\nimport uuid", 1)

helper_anchor = '''def flush_job_results_for_turn_end(item_id: str, conversation_key: str = "") -> bool:
    entries = _pop_buffered_job_results(item_id, conversation_key)
    return flush_background_job_results_for_entries(item_id, entries)
'''
helpers = '''

# Idle-time job result coalescing: when a background job finishes and sibling
# jobs for the same item are still running, hold the result in a short window
# so siblings finishing soon can share ONE follow-up turn. Sequential
# single-job flows flush immediately (zero added latency).

_active_background_jobs_lock = threading.Lock()
_active_background_jobs: dict[str, set[str]] = {}
_job_result_coalesce_lock = threading.Lock()
_job_result_coalesce: dict[tuple[str, str], dict[str, Any]] = {}


def _register_active_background_job(item_id: str, job_token: str) -> None:
    with _active_background_jobs_lock:
        _active_background_jobs.setdefault(str(item_id), set()).add(job_token)


def _unregister_active_background_job(item_id: str, job_token: str) -> int:
    with _active_background_jobs_lock:
        bucket = _active_background_jobs.get(str(item_id))
        if bucket is None:
            return 0
        bucket.discard(job_token)
        sibling_count = len(bucket)
        if not bucket:
            _active_background_jobs.pop(str(item_id), None)
        return sibling_count


def _coalesce_window_seconds() -> float:
    try:
        from app.core.config import settings

        return float(
            getattr(settings, "ROBOT_JOB_RESULT_COALESCE_WINDOW_SECONDS", 20.0) or 0.0
        )
    except Exception:
        return 20.0


def enqueue_job_result_flush(
    item_id: str, entry: dict[str, Any], *, sibling_count: int
) -> None:
    window = _coalesce_window_seconds()
    if window <= 0:
        flush_background_job_results_for_entries(item_id, [entry])
        return
    key = (
        str(item_id),
        str(entry.get("conversation_key") or entry.get("reply_ticket_id") or ""),
    )
    flush_entries: list[dict[str, Any]] | None = None
    with _job_result_coalesce_lock:
        state = _job_result_coalesce.get(key)
        if state is not None:
            state["entries"].append(entry)
            if sibling_count <= 0:
                timer = state.get("timer")
                if timer is not None:
                    timer.cancel()
                flush_entries = list(state["entries"])
                _job_result_coalesce.pop(key, None)
        elif sibling_count <= 0:
            flush_entries = [entry]
        else:
            timer = threading.Timer(
                window, _flush_coalesced_job_results, args=(str(item_id), key)
            )
            timer.daemon = True
            _job_result_coalesce[key] = {"entries": [entry], "timer": timer}
            timer.start()
            debug_log(
                "[LocalMCPServer] job result coalescing: holding result up to "
                f"{window:.0f}s for sibling jobs, item={item_id}, "
                f"active_siblings={sibling_count}"
            )
    if flush_entries:
        flush_background_job_results_for_entries(item_id, flush_entries)


def _flush_coalesced_job_results(item_id: str, key: tuple[str, str]) -> None:
    with _job_result_coalesce_lock:
        state = _job_result_coalesce.pop(key, None)
    if not state:
        return
    entries = state.get("entries") or []
    if not entries:
        return
    debug_log(
        "[LocalMCPServer] job result coalesce window expired: flushing "
        f"{len(entries)} result(s), item={item_id}"
    )
    flush_background_job_results_for_entries(item_id, entries)
'''
assert helper_anchor in src, "helper anchor not found"
assert "enqueue_job_result_flush" not in src, "helpers already present"
src = src.replace(helper_anchor, helper_anchor + helpers, 1)

method_anchor = "    def _start_background_job_thread("
method_pos = src.index(method_anchor)
start_marker = "        def worker() -> None:\n"
start_pos = src.index(start_marker, method_pos)
end_marker = "            flush_background_job_results_for_entries(item_id, [entry])\n"
end_pos = src.index(end_marker, start_pos) + len(end_marker)
worker_block = src[start_pos:end_pos]

lines = worker_block.split("\n")
body_lines = lines[1:]
dedented = []
for ln in body_lines:
    if ln.startswith("    "):
        dedented.append(ln[4:])
    else:
        dedented.append(ln)
body_text = "\n".join(dedented)
cmark = "        # Always deliver immediately"
cpos = body_text.rindex(cmark)
body_text = body_text[:cpos] + "        return entry\n"

new_method = '''    def _background_job_worker_body(
        self,
        *,
        connection,
        request_kwargs: dict,
        item_id: str,
        command: str,
        agent_session,
        robot_job_context: dict | None,
        reply_ticket_id: str,
        pending_robot_reply_id: str | None,
        workflow_id: str,
    ) -> dict | None:
''' + body_text

new_worker = '''        def worker() -> None:
            job_token = uuid.uuid4().hex
            _register_active_background_job(item_id, job_token)
            entry = None
            try:
                entry = self._background_job_worker_body(
                    connection=connection,
                    request_kwargs=request_kwargs,
                    item_id=item_id,
                    command=command,
                    agent_session=agent_session,
                    robot_job_context=robot_job_context,
                    reply_ticket_id=reply_ticket_id,
                    pending_robot_reply_id=pending_robot_reply_id,
                    workflow_id=workflow_id,
                )
            except Exception as exc:
                debug_log(
                    f"[LocalMCPServer] background job worker error: item={item_id}, error={exc}"
                )
            finally:
                sibling_count = _unregister_active_background_job(item_id, job_token)
                if entry is not None:
                    enqueue_job_result_flush(item_id, entry, sibling_count=sibling_count)
'''

src = src[:start_pos] + new_worker + src[end_pos:]
src = src.replace(method_anchor, new_method + "\n" + method_anchor, 1)
p.write_text(src, encoding="utf-8")
print("local_server patched")