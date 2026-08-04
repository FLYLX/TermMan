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

p = r"backend\tests\services\test_robot_service.py"
t, crlf = load(p)

old = """import asyncio
import sys
import types"""
new = """import asyncio
import sys
import time
import types"""
t = replace_once(t, old, new, "import time")

old = """    if mentioned_bot and mentions is None:
        mentions = [{"qq": TEST_BOT_SELF_ID}]"""
new = """    if mentioned_bot and mentions is None:
        mentions = [{"qq": TEST_BOT_SELF_ID, "name": "TestBot"}]"""
t = replace_once(t, old, new, "fixture mention name")

old = """    monkeypatch.setattr(robot_service, "_enqueue_chat_job", fake_enqueue_chat_job)
    return captured


def _process_captured_chat_job(monkeypatch, job) -> list[str]:"""
new = """    monkeypatch.setattr(robot_service, "_enqueue_chat_job", fake_enqueue_chat_job)
    return captured


def _simulate_worker_pickup(monkeypatch, job) -> None:
    snapshot = dict(robot_service._active_dispatch_jobs)
    tracking_key = job.job_id or "test-active-job"
    with robot_service._lock:
        robot_service._active_dispatch_jobs[tracking_key] = (time.monotonic(), job)

    def _restore_active_dispatch_jobs() -> None:
        with robot_service._lock:
            robot_service._active_dispatch_jobs.clear()
            robot_service._active_dispatch_jobs.update(snapshot)

    monkeypatch.finalizer(_restore_active_dispatch_jobs)


def _process_captured_chat_job(monkeypatch, job) -> list[str]:"""
t = replace_once(t, old, new, "worker pickup helper")

old = """    assert first.ignored is False
    first_job = queued_jobs[-1]

    second = robot_service.handle_inbound_message("""
new = """    assert first.ignored is False
    first_job = queued_jobs[-1]
    _simulate_worker_pickup(monkeypatch, first_job)

    second = robot_service.handle_inbound_message("""
t = replace_once(t, old, new, "pickup: superseding test")

old = """    assert first.ignored is False

    active_plain = robot_service.handle_inbound_message("""
new = """    assert first.ignored is False
    first_job = queued_jobs[-1]
    _simulate_worker_pickup(monkeypatch, first_job)

    active_plain = robot_service.handle_inbound_message("""
t = replace_once(t, old, new, "pickup: continue-after-no-reply test")

old = """    assert len(queued_jobs) == 1
    first_job = queued_jobs[-1]
    assert "[CQ:image" not in first_job.message"""
new = """    assert len(queued_jobs) == 1
    first_job = queued_jobs[-1]
    _simulate_worker_pickup(monkeypatch, first_job)
    assert "[CQ:image" not in first_job.message"""
t = replace_once(t, old, new, "pickup: image segments test")

old = """    assert first.ignored is False
    first_job = queued_jobs[-1]

    for index in range(1, 8):"""
new = """    assert first.ignored is False
    first_job = queued_jobs[-1]
    _simulate_worker_pickup(monkeypatch, first_job)

    for index in range(1, 8):"""
t = replace_once(t, old, new, "pickup: latest five test")

old = '"[Robot message; conversation=group:g1; trigger=mention_bot; sender=Alice (u1)]\\n"'
n = t.count(old)
assert n == 2, "alice header expected 2, found %d" % n
new = '"[Robot message; conversation=group:g1; trigger=mention_bot; sender=Alice (u1); mentions=TestBot (10001) (you)]\\n"'
t = t.replace(old, new)

old = '"[Robot message; conversation=group:g1; trigger=mention_bot; sender=Bob (u3)]\\n"'
new = '"[Robot message; conversation=group:g1; trigger=mention_bot; sender=Bob (u3); mentions=TestBot (10001) (you)]\\n"'
t = replace_once(t, old, new, "bob header")

old = """    robot_service._process_chat_job(job)

    assert captured_messages == [job.message]"""
new = """    robot_service._process_chat_job(job)

    assert len(captured_messages) == 1
    assert "wake after delay" in captured_messages[0]"""
t = replace_once(t, old, new, "corrective turn assertion")

old = """    errors: list[str] = []
    monkeypatch.setattr(
        service,
        "_record_and_send_job_error",
        lambda _job, message: errors.append(message),
    )

    reaped = service.reap_stuck_dispatch_jobs()

    assert reaped == 1
    assert errors and "\u8d85\u65f6" in errors[0]
    assert "stuck-1" not in service._active_dispatch_jobs"""
new = """    errors: list[str] = []
    monkeypatch.setattr(
        service,
        "_record_job_timeout_silent",
        lambda _job, detail: errors.append(detail),
    )

    reaped = service.reap_stuck_dispatch_jobs()

    assert reaped == 1
    assert errors and "hard timeout" in errors[0]
    assert "stuck-1" not in service._active_dispatch_jobs"""
t = replace_once(t, old, new, "reap silent timeout")

old = """    assert job.reply_target.metadata["allow_multiple_reply_messages"] is False
    assert "Are you there?" in job.message
    assert "Reply now" in job.message
    assert "one evolving intent" in job.message"""
new = """    assert job.reply_target.metadata["allow_multiple_reply_messages"] is False
    # Latest-instruction-wins: the older same-sender line is superseded.
    assert "Are you there?" not in job.message
    assert "Reply now" in job.message
    assert "one evolving intent" in job.message"""
t = replace_once(t, old, new, "superseded batch assertion")
save(p, t, crlf)
print("test_robot_service.py OK")
print("ALL DONE")
