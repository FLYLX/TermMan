path = '/app/backend/app/services/agent/terminal_noise.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Remove the dead code
dead = '''

PROMPT_ONLY_RE = re.compile(
    r"^[\s>#$%]*$",
)


def is_prompt_only_content(content: str) -> bool:
    """True if content is nothing but bare shell/REPL prompt characters."""
    cleaned = _strip_terminal_controls(content or "").strip()
    if not cleaned:
        return True
    return bool(PROMPT_ONLY_RE.match(cleaned))
'''

if dead in content:
    content = content.replace(dead, '\n')
    print("OK: removed dead code")
else:
    print("WARN: exact block not found, trying line-by-line")
    content = content.replace('PROMPT_ONLY_RE = re.compile(\n    r"^[\s>#$%]*$",\n)\n', '')
    content = content.replace('def is_prompt_only_content(content: str) -> bool:', '')

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("DONE")
