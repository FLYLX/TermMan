# -*- coding: utf-8 -*-
import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
p = r"E:\dev\TermPaws\dev\TermPaws\backend\app\plugins\robot\service.py"
s = open(p, encoding="utf-8").read()

old = '''            task_control_message = bool(TASK_CONTROL_MESSAGE_RE.search(message_text))
            if (
                command.mode == "chat"
                and controller_gate.processing
                and reply_context_active
                and not task_control_message
            ):'''
new = '''            task_control_message = bool(TASK_CONTROL_MESSAGE_RE.search(message_text))
            # Merge chat into a running turn only when a dispatch turn is
            # actually running/queued. Background jobs alone must not hold
            # chat hostage: jobs run in the daemon while the backend is free,
            # so an incoming chat message starts its own turn immediately.
            turn_actively_busy = self.conversation_has_active_dispatch(
                robot.id, conversation_key
            )
            if (
                command.mode == "chat"
                and turn_actively_busy
                and reply_context_active
                and not task_control_message
            ):'''
assert s.count(old) == 1, f"gate anchor={s.count(old)}"
s = s.replace(old, new)
open(p, "w", encoding="utf-8", newline="").write(s)
print("gate fix: OK")
