path = '/app/backend/app/services/agent/stream_manager.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Add import
old_import = 'from app.services.agent.terminal_noise import is_progress_noise_content'
new_import = 'from app.services.agent.terminal_noise import is_progress_noise_content, is_prompt_only_content'

if old_import in content:
    content = content.replace(old_import, new_import)
    print("OK: updated import")
else:
    print("ERROR: import not found")
    import sys; sys.exit(1)

# Add prompt-only check in process_stream, right after the has_filtered_output check
old_check = '''        has_filtered_output = bool(filtered_output and filtered_output.strip())
        has_raw_output = bool(raw_output and raw_output.strip())
        if not has_filtered_output and not (has_raw_output and session.has_pending_command()):
            logger.debug("[StreamManager] No usable output for agent processing, skipping")
            return'''

new_check = '''        has_filtered_output = bool(filtered_output and filtered_output.strip())
        has_raw_output = bool(raw_output and raw_output.strip())
        if not has_filtered_output and not (has_raw_output and session.has_pending_command()):
            logger.debug("[StreamManager] No usable output for agent processing, skipping")
            return
        if has_filtered_output and is_prompt_only_content(filtered_output):
            logger.debug("[StreamManager] Prompt-only terminal output, skipping: item=%s", item_id)
            return'''

if old_check in content:
    content = content.replace(old_check, new_check)
    print("OK: added prompt-only filter")
else:
    print("ERROR: check block not found")
    import sys; sys.exit(1)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("DONE")
