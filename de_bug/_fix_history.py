# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

def patch(path, repls):
    src = open(path, encoding="utf-8").read()
    for old, new in repls:
        n = src.count(old)
        if n != 1:
            print(f"FAIL {path}: anchor count={n} for {old[:70]!r}")
            sys.exit(1)
        src = src.replace(old, new)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(src)
    print(f"OK {path}: {len(repls)} replacement(s)")

CHAT = r"backend\app\api\routes\chat.py"

patch(CHAT, [
# A) constant for robot-side single callback prefix
(
'''INTERNAL_QQ_BACKGROUND_JOB_BATCH_PREFIX = "[Background job results batch:"''',
'''INTERNAL_QQ_BACKGROUND_JOB_BATCH_PREFIX = "[Background job results batch:"
INTERNAL_QQ_BACKGROUND_JOB_ROBOT_PREFIX = "[后台终端任务结果 - 来自 QQ 会话]"'''
),
# B) include robot single-callback prefix in internal detection
(
'''    return (
        text.startswith(INTERNAL_QQ_BACKGROUND_JOB_PREFIX)
        or text.startswith(INTERNAL_QQ_BACKGROUND_JOB_BATCH_PREFIX)
        or text.startswith(INTERNAL_AGENT_RETRY_PREFIX)
    )''',
'''    return (
        text.startswith(INTERNAL_QQ_BACKGROUND_JOB_PREFIX)
        or text.startswith(INTERNAL_QQ_BACKGROUND_JOB_ROBOT_PREFIX)
        or text.startswith(INTERNAL_QQ_BACKGROUND_JOB_BATCH_PREFIX)
        or text.startswith(INTERNAL_AGENT_RETRY_PREFIX)
    )'''
),
# C) persist callback content as the user message for job-callback rounds
(
'''    if not internal_agent_callback:
        user_message_type = "qq_user" if normalized_source_type == SOURCE_QQ else "chat_user"
        # The model gets the fully composed message (sender cards, live
        # context, memories...), but the chat history and the web UI should
        # only show the raw text the QQ user actually sent.
        display_content = message
        if normalized_source_type == SOURCE_QQ:
            display_content = _qq_display_text(reply_ticket.request_message or message)''',
'''    _stripped_message = str(message or "").lstrip()
    background_job_callback = internal_agent_callback and (
        _stripped_message.startswith(INTERNAL_QQ_BACKGROUND_JOB_PREFIX)
        or _stripped_message.startswith(INTERNAL_QQ_BACKGROUND_JOB_ROBOT_PREFIX)
        or _stripped_message.startswith(INTERNAL_QQ_BACKGROUND_JOB_BATCH_PREFIX)
    )
    if not internal_agent_callback or background_job_callback:
        user_message_type = "qq_user" if normalized_source_type == SOURCE_QQ else "chat_user"
        # The model gets the fully composed message (sender cards, live
        # context, memories...), but the chat history and the web UI should
        # only show the raw text the QQ user actually sent. Background job
        # callback rounds have no user text of their own; persist the
        # callback content itself so the history stays self-consistent.
        # (Otherwise the ticket's original request would be re-persisted
        # once per callback and later turns lose track of which round they
        # are answering.)
        display_content = message
        if background_job_callback:
            display_content = _qq_display_text(message)
        elif normalized_source_type == SOURCE_QQ:
            display_content = _qq_display_text(reply_ticket.request_message or message)'''
),
])
print("HISTORY FIX APPLIED")
