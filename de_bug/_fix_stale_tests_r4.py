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

p = r"backend\app\plugins\robot\service.py"
t, crlf = load(p)

old = """        index = 1
        for entry in entries[:PENDING_CHAT_QUEUE_LIMIT]:
            if first_item_id is None:
                first_item_id = entry.item_id"""
new = """        index = 1
        for entry in entries[-PENDING_CHAT_QUEUE_LIMIT:]:
            if first_item_id is None:
                first_item_id = entry.item_id"""
t = replace_once(t, old, new, "snapshot latest-N")

old = """            if len(text) > 220:
                text = f"{text[:217]}..."
            lines.append(
                f"{index}. sender={entry.sender_label}; sender_key={entry.sender_key}; "
                f"trigger={entry.trigger_reason}: {text}"
            )
            index += 1"""
assert t.count(old) == 1, "batch text loop not found"
new = old.replace(
    "for entry in entries[:PENDING_CHAT_QUEUE_LIMIT]:",
    "for entry in entries[-PENDING_CHAT_QUEUE_LIMIT:]",
)
t = t.replace(old, new)
save(p, t, crlf)
print("service.py OK")

p = r"backend\tests\services\test_robot_service.py"
t, crlf = load(p)

old = """    assert active_plain.reason == "queued_pending"
    assert second_wakeup.reason == "queued"
    assert third_wakeup.reason == "queued"
    assert len(queued_jobs) == 3
    snapshots = robot_service.conversation_controller_snapshots(
        {robot.id},
        item_ids={item.id},
    )
    assert snapshots[0]["pending_count"] == 1"""
new = """    # Every follow-up (plain chat or fresh @mention) merges into the pending
    # queue while a turn is in flight; the turn-end drain starts one follow-up.
    assert active_plain.reason == "queued_pending"
    assert second_wakeup.reason == "queued_pending"
    assert third_wakeup.reason == "queued_pending"
    assert len(queued_jobs) == 1
    snapshots = robot_service.conversation_controller_snapshots(
        {robot.id},
        item_ids={item.id},
    )
    assert snapshots[0]["pending_count"] == 3"""
t = replace_once(t, old, new, "continue-after-no-reply semantics")

old = """    assert "1. sender=Carol (u3); trigger=active_chat_window: look now" in pending_message"""
new = """    assert (
        "1. sender=Carol (u3); sender_key=onebot_v11:group:g-image-mixed:u3; "
        "trigger=active_chat_window: look now"
    ) in pending_message"""
t = replace_once(t, old, new, "image pending line format")
save(p, t, crlf)
print("test_robot_service.py OK")
print("ALL DONE")
