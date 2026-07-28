path = '/app/backend/app/services/agent/session.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Add debug logging to _call_llm
old = '''        effective_tools = agent.get_tools_for_litellm() if tools is None else tools
        kwargs = build_litellm_completion_kwargs('''

new = '''        effective_tools = agent.get_tools_for_litellm() if tools is None else tools
        try:
            _msg_chars = sum(len(str(m.get("content", ""))) for m in messages)
            _tool_chars = len(str(effective_tools)) if effective_tools else 0
            logger.info(
                "[LLM_REQ] msgs=%d msg_chars=%d tools=%d tool_chars=%d",
                len(messages), _msg_chars, len(effective_tools) if effective_tools else 0, _tool_chars,
            )
        except Exception:
            pass
        kwargs = build_litellm_completion_kwargs('''

if old in content:
    content = content.replace(old, new)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)
    print("OK: added LLM request debug log")
else:
    print("ERROR: not found")
