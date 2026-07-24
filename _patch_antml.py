import pathlib

path = pathlib.Path('backend/app/core/tool_markup.py')
content = path.read_text(encoding='utf-8')

# Build the antml tag strings using chr to avoid shell issues
ANTML_OPEN = chr(60) + 'antml:tool_call' + chr(62)
ANTML_CLOSE = chr(60) + '/antml:tool_call' + chr(62)

new_code = f'''

# ---------------------------------------------------------------------------
# Anthropic-style {ANTML_OPEN} fallback extraction
# ---------------------------------------------------------------------------
# Some OpenAI-compatible proxies (especially those routing to Claude/Anthropic
# models) leak the native {ANTML_OPEN} markup into the streamed content instead
# of emitting proper delta.tool_calls.  We detect this pattern, extract the
# tool name and arguments, and strip the markup from visible text.

_ANTML_INVOKE_RE = re.compile(
    r''' + ref'"{ANTML_OPEN}"' + r''''
    r"(?P<name>[a-zA-Z_][a-zA-Z0-9_]*)"
    r"\s*\(\s*(?P<args>[^)]*)\s*\)"
    r"[^']*?"
    r''' + ref'"(?:{ANTML_CLOSE}|{ANTML_OPEN}|$)"' + r''',
    re.DOTALL,
)

_ANTML_ANY_TAG_RE = re.compile(
    r"</?antml:tool_call[^>]*>",
    re.IGNORECASE,
)


def contains_antml_tool_markup(value: Any) -> bool:
    return bool(_ANTML_ANY_TAG_RE.search(str(value or "")))


def strip_antml_tool_markup(value: Any) -> str:
    text = str(value or "")
    if not contains_antml_tool_markup(text):
        return text
    cleaned = _ANTML_INVOKE_RE.sub("", text)
    cleaned = _ANTML_ANY_TAG_RE.sub("", cleaned)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def extract_antml_tool_calls(
    value: Any,
    *,
    allowed_tool_names: set[str],
) -> tuple[str, list[dict[str, Any]]]:
    text = str(value or "")
    if not contains_antml_tool_markup(text):
        return text, []

    tool_calls: list[dict[str, Any]] = []
    for match in _ANTML_INVOKE_RE.finditer(text):
        tool_name = match.group("name").strip()
        if not tool_name or tool_name not in allowed_tool_names:
            continue
        raw_args = match.group("args").strip()
        arguments: dict[str, Any] = {}
        if raw_args:
            try:
                parsed = json.loads(raw_args)
                if isinstance(parsed, dict):
                    arguments = parsed
            except (json.JSONDecodeError, ValueError):
                arguments = {"input": raw_args}

        tool_calls.append(
            {
                "id": f"call_antml_{len(tool_calls)}",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(arguments, ensure_ascii=False),
                },
            }
        )

    return strip_antml_tool_markup(text), tool_calls
'''

content += new_code
path.write_text(content, encoding='utf-8')
print('Patched tool_markup.py successfully')
print(f'Added extract_antml_tool_calls function')
