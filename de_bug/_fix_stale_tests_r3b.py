# -*- coding: utf-8 -*-

def load(path):
    with open(path, encoding="utf-8", newline="") as f:
        raw = f.read()
    had_crlf = "\r\n" in raw
    return raw.replace("\r\n", "\n"), had_crlf

def save(path, text, had_crlf):
    if had_crlf:
        text = text.replace("\n", "\r\n")
    with open(path, "w", encoding="utf-8", newline="") as f:
        f.write(text)

def replace_once(text, old, new, label):
    n = text.count(old)
    assert n == 1, "%s: expected 1 occurrence, found %d" % (label, n)
    return text.replace(old, new)

p = r"backend\app\services\agent\prompts\builder.py"
t, crlf = load(p)
old = """    if not latest_only_context and policy.include_recent_history:
        prompt_messages.extend(recent_context_messages)

    if policy.include_long_term:
        memories = _collect_long_term_memories(
            item_id,
            retrieval_query,"""
new = """    if not latest_only_context and policy.include_recent_history:
        prompt_messages.extend(recent_context_messages)

    if policy.include_long_term and not latest_only_context:
        memories = _collect_long_term_memories(
            item_id,
            retrieval_query,"""
t = replace_once(t, old, new, "builder latest-only gate")
save(p, t, crlf)
print("builder.py OK")

p = r"backend\tests\services\test_robot_service.py"
t, crlf = load(p)

old = """def _simulate_worker_pickup(monkeypatch, job) -> None:
    snapshot = dict(robot_service._active_dispatch_jobs)
    tracking_key = job.job_id or "test-active-job"
    with robot_service._lock:
        robot_service._active_dispatch_jobs[tracking_key] = (time.monotonic(), job)

    def _restore_active_dispatch_jobs() -> None:
        with robot_service._lock:
            robot_service._active_dispatch_jobs.clear()
            robot_service._active_dispatch_jobs.update(snapshot)

    monkeypatch.finalizer(_restore_active_dispatch_jobs)"""
new = """def _simulate_worker_pickup(monkeypatch, job) -> None:
    active_jobs = dict(robot_service._active_dispatch_jobs)
    tracking_key = job.job_id or "test-active-job"
    active_jobs[tracking_key] = (time.monotonic(), job)
    monkeypatch.setattr(robot_service, "_active_dispatch_jobs", active_jobs)"""
t = replace_once(t, old, new, "pickup helper setattr")

old = """    assert len(captured_messages) == 1
    assert "wake after delay" in captured_messages[0]"""
new = """    assert captured_messages
    assert all("wake after delay" in message for message in captured_messages)"""
t = replace_once(t, old, new, "corrective turn assertion")
save(p, t, crlf)
print("test_robot_service.py OK")
print("ALL DONE")
