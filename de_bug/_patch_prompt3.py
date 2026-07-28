path = '/app/backend/app/services/agent/stream_manager.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

old_filter = '''        if has_filtered_output and is_prompt_only_content(filtered_output):
            logger.debug("[StreamManager] Prompt-only terminal output, skipping: item=%s", item_id)
            return'''

new_filter = '''        if has_filtered_output and is_prompt_only_content(filtered_output) and not session.has_pending_command():
            logger.debug("[StreamManager] Prompt-only terminal output, skipping: item=%s", item_id)
            return'''

if old_filter in content:
    content = content.replace(old_filter, new_filter)
    print("OK: fixed prompt-only filter to respect pending commands")
else:
    print("ERROR: filter not found")
    import sys; sys.exit(1)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("DONE")
