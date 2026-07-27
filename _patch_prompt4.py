# 1. Remove is_prompt_only_content from stream_manager.py
path = '/app/backend/app/services/agent/stream_manager.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Remove the import addition
content = content.replace(
    'from app.services.agent.terminal_noise import is_progress_noise_content, is_prompt_only_content',
    'from app.services.agent.terminal_noise import is_progress_noise_content'
)

# Remove the filter block
content = content.replace(
    '''        if has_filtered_output and is_prompt_only_content(filtered_output) and not session.has_pending_command():
            logger.debug("[StreamManager] Prompt-only terminal output, skipping: item=%s", item_id)
            return''',
    ''
)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("OK: removed is_prompt_only_content from stream_manager")

# 2. Fix _append_terminal_part to strip prompt prefixes
old_append = '''    def _append_terminal_part(self, batch: PendingTerminalBatch, content: str):
        normalized = content.strip("\\n")
        if normalized:
            batch.parts.append(normalized)
            batch.last_update = datetime.now()'''

new_append = '''    def _append_terminal_part(self, batch: PendingTerminalBatch, content: str):
        normalized = content.strip("\\n")
        if normalized:
            normalized = _strip_prompt_prefix(normalized)
        if normalized:
            batch.parts.append(normalized)
            batch.last_update = datetime.now()'''

if old_append in content:
    content = content.replace(old_append, new_append)
    print("OK: updated _append_terminal_part")
else:
    print("ERROR: _append_terminal_part not found")

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)

# 3. Add _strip_prompt_prefix helper at module level
# Find a good insertion point - after imports
import_end = content.find('\n\nclass ')
if import_end == -1:
    import_end = content.find('\n\nlogger')

helper = '''

_PROMPT_PREFIX_RE = re.compile(r"^(?:>\\s?|\\$\\s?|#\\s?){1,3}")


def _strip_prompt_prefix(text: str) -> str:
    """Strip leading shell/REPL prompt characters from each line.
    Lines that become empty after stripping are removed."""
    lines = text.split("\\n")
    cleaned = []
    for line in lines:
        stripped = _PROMPT_PREFIX_RE.sub("", line).rstrip()
        if stripped:
            cleaned.append(stripped)
    return "\\n".join(cleaned)

'''

# Need to add 're' import if not present
if 'import re' not in content:
    content = 'import re\n' + content

# Insert helper before the class definition
content = content[:import_end] + helper + content[import_end:]

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("OK: added _strip_prompt_prefix helper")
print("DONE")
