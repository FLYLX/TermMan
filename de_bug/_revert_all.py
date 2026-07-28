import sys

# Revert stream_manager.py
path = r"E:\dev\TermMan\dev\TermMan\backend\app\services\agent\stream_manager.py"
with open(path, "r", encoding="utf-8") as f:
    content = f.read()

old = """        elif session.has_pending_command():
            session.mark_waiting_terminal_feedback()
        else:
            # Idle with no pending command: buffer silently, do NOT trigger
            # a new agent turn.  The output stays in the terminal log and is
            # injected passively into the next real turn's context.
            logger.debug(
                "[StreamManager] Idle buffer (no turn) for item=%s, len=%d",
                item_id, len(filtered_output or ""),
            )
            return"""

new = """        elif session.has_pending_command():
            session.mark_waiting_terminal_feedback()
        else:
            session.mark_collecting()"""

if old not in content:
    print("ERROR: stream_manager revert block not found")
    sys.exit(1)
content = content.replace(old, new)
with open(path, "w", encoding="utf-8") as f:
    f.write(content)
print("OK: stream_manager reverted")

# Revert chat.py - remove passive injection
path2 = r"E:\dev\TermMan\dev\TermMan\backend\app\api\routes\chat.py"
with open(path2, "r", encoding="utf-8") as f:
    content2 = f.read()

# Remove the injection call
content2 = content2.replace(
    "    _inject_active_jobs_prompt_context(item_id, messages)\n    _inject_recent_terminal_output(item_id, messages)",
    "    _inject_active_jobs_prompt_context(item_id, messages)"
)

# Remove the helper function
fn_block = """TERMINAL_LOG_INJECT_LINES = 20


def _inject_recent_terminal_output(item_id: str, messages: list[dict[str, Any]]) -> None:
    try:
        from app.services.log_manager import LogManager

        log_content = LogManager().get_last_lines(item_id, TERMINAL_LOG_INJECT_LINES)
        if not log_content or not log_content.strip():
            return
        messages.insert(
            max(len(messages) - 1, 0),
            {
                "role": "system",
                "content": (
                    f"[Recent interactive terminal output (last {TERMINAL_LOG_INJECT_LINES} lines)]\\n"
                    f"{log_content.strip()}\\n"
                    "This is live terminal context. Use it to understand what happened "
                    "recently in the terminal, but do not react to it unless the user "
                    "asks or it is relevant to the current request."
                ),
            },
        )
    except Exception:
        pass


def generate_stream("""

content2 = content2.replace(fn_block, "def generate_stream(")

with open(path2, "w", encoding="utf-8") as f:
    f.write(content2)
print("OK: chat.py reverted")
