path = '/app/backend/app/services/agent/session.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Add import at the top (after other imports from app.services.agent)
old_import = 'from app.services.agent.tool_selection import select_tools_for_turn'
new_import = '''from app.services.agent.tool_selection import select_tools_for_turn
from app.services.agent.token_usage import token_usage_tracker'''

if old_import in content:
    content = content.replace(old_import, new_import)
    print("OK: added import")
else:
    print("ERROR: import anchor not found")
    import sys; sys.exit(1)

# Hook into _call_llm - record usage after successful completion
old_call = '''        last_exc: BaseException | None = None
        for attempt in range(3):
            try:
                return completion(**kwargs)'''

new_call = '''        last_exc: BaseException | None = None
        for attempt in range(3):
            try:
                response = completion(**kwargs)
                try:
                    usage = getattr(response, "usage", None)
                    if usage:
                        token_usage_tracker.record(
                            self.item_id,
                            str(agent._context.model or "unknown"),
                            int(getattr(usage, "prompt_tokens", 0) or 0),
                            int(getattr(usage, "completion_tokens", 0) or 0),
                            int(getattr(usage, "total_tokens", 0) or 0),
                        )
                except Exception:
                    pass
                return response'''

if old_call in content:
    content = content.replace(old_call, new_call)
    print("OK: hooked _call_llm")
else:
    print("ERROR: _call_llm anchor not found")
    import sys; sys.exit(1)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("DONE")
