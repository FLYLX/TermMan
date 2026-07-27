path = '/app/backend/app/services/agent/stream_manager.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix: the helper was inserted in the middle of the dataclass
# Remove the misplaced helper
bad_block = '''
_PROMPT_PREFIX_RE = re.compile(r"^(?:>\s?|\$\s?|#\s?){1,3}")


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

content = content.replace(bad_block, '')

# Fix the broken line
content = content.replace('timer: threading.Timer | No', 'timer: threading.Timer | None = None')

# Now insert the helper at the right place - after all imports, before first class
# Find the line with 'logger = ' which is typically after imports
import re as re_mod
logger_match = re_mod.search(r'\nlogger = ', content)
if logger_match:
    insert_pos = logger_match.start()
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
    content = content[:insert_pos] + helper + content[insert_pos:]
    print("OK: inserted helper before logger")
else:
    print("ERROR: logger line not found")
    import sys; sys.exit(1)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("DONE")
