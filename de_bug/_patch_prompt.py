path = '/app/backend/app/services/agent/terminal_noise.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

# Add prompt-only detection at the end
addition = '''

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

content = content.rstrip() + "\n" + addition
with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("OK: added is_prompt_only_content")
