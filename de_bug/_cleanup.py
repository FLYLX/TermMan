filepath = r"E:\dev\TermMan\dev\TermMan\backend\app\services\agent\session.py"
with open(filepath, "r", encoding="utf-8") as f:
    content = f.read()

changes = 0

# Remove debug file writes from _process_chat_input
old = '''    def _process_chat_input(self, input_msg: InputMessage, agent: Agent):
        with open("/tmp/token_debug.log", "a") as _tdf:
            _tdf.write(f"_process_chat_input called\\n")
        if input_msg.callback:'''
new = '''    def _process_chat_input(self, input_msg: InputMessage, agent: Agent):
        if input_msg.callback:'''
if old in content:
    content = content.replace(old, new, 1)
    changes += 1

# Remove debug around _call_llm
old2 = '''                with open("/tmp/token_debug.log", "a") as _tdf:
                    _tdf.write(f"about to call _call_llm\\n")
                response = self._call_llm(agent, messages, tools=tools)
                with open("/tmp/token_debug.log", "a") as _tdf:
                    _tdf.write(f"_call_llm returned\\n")'''
new2 = '''                response = self._call_llm(agent, messages, tools=tools)'''
if old2 in content:
    content = content.replace(old2, new2, 1)
    changes += 1

# Remove debug file write from _call_llm but keep the tracker
old3 = '''                    usage = getattr(response, "usage", None)
                    with open("/tmp/token_debug.log", "a") as _tdf:
                        _tdf.write(f"usage={usage} type={type(usage).__name__}\\n")
                    logger.warning("[TokenDebug] usage=%s type=%s", usage, type(usage).__name__)
                    if usage:'''
new3 = '''                    usage = getattr(response, "usage", None)
                    if usage:'''
if old3 in content:
    content = content.replace(old3, new3, 1)
    changes += 1

# Also remove the [LLM_REQ] debug log
old4 = '''        try:
            _msg_chars = sum(len(str(m.get("content", ""))) for m in messages)
            _tool_chars = len(str(effective_tools)) if effective_tools else 0
            logger.info(
                "[LLM_REQ] msgs=%d msg_chars=%d tools=%d tool_chars=%d",
                len(messages), _msg_chars, len(effective_tools) if effective_tools else 0, _tool_chars,
            )
        except Exception:
            pass
        kwargs = build_litellm_completion_kwargs('''
new4 = '''        kwargs = build_litellm_completion_kwargs('''
if old4 in content:
    content = content.replace(old4, new4, 1)
    changes += 1

with open(filepath, "w", encoding="utf-8", newline="\n") as f:
    f.write(content)
print(f"Cleaned {changes} debug patches from session.py")