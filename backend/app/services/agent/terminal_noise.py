import re

ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
ERROR_HINT_RE = re.compile(
    r"\b(?:error|failed|failure|exception|traceback|denied|not found|timed out|timeout|aborted|cancelled)\b",
    re.IGNORECASE,
)
PROGRESS_LINE_PATTERNS = (
    re.compile(r"^\s*%\s+Total\s+%\s+Received\b", re.IGNORECASE),
    re.compile(
        r"^\s*\d{1,3}\s+\d+(?:\.\d+)?[kmg]?\s+\d{1,3}\s+\d+(?:\.\d+)?[kmg]?\s+\d{1,3}\s+",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*\d{1,3}%\|.*\|"),
    re.compile(r".*\d{1,3}%.*(?:\[[\s=>#.-]+\]|[=#>]{2,}|\|.*\|).*"),
    re.compile(r"^\s*\d+(?:\.\d+)?\s*[KMG]B?\s+.*\d{1,3}%", re.IGNORECASE),
    re.compile(
        r"^\s*(?:downloading|downloaded|fetching|receiving|extracting|installing|building|preparing)\b.*(?:\d{1,3}%|\d+(?:\.\d+)?\s*(?:kb|mb|gb)|/s|it/s)",
        re.IGNORECASE,
    ),
    re.compile(r"^\s*(?:get|hit|ign):\d+\s+", re.IGNORECASE),
    re.compile(r"^\s*(?:\||/|-|\\)\s*$"),
    re.compile(r"^\s*(?:\||/|-|\\)\s+(?:download|fetch|install|build|extract)\b", re.IGNORECASE),
)


def _strip_terminal_controls(value: str) -> str:
    value = ANSI_ESCAPE_RE.sub("", value or "")
    value = value.replace("\b", "")
    value = CONTROL_CHARS_RE.sub("", value)
    return value


def split_terminal_lines(content: str) -> list[str]:
    cleaned = _strip_terminal_controls(content)
    return [line.strip() for line in re.split(r"[\r\n]+", cleaned) if line.strip()]


def is_progress_noise_line(line: str) -> bool:
    stripped = _strip_terminal_controls(line).strip()
    if not stripped:
        return False
    if ERROR_HINT_RE.search(stripped):
        return False
    if any(pattern.match(stripped) for pattern in PROGRESS_LINE_PATTERNS):
        return True
    return bool(
        re.search(r"\d{1,3}%", stripped)
        and re.search(r"(?:/s|eta|remaining|\[[\s=>#.-]+\])", stripped, re.IGNORECASE)
    )


def is_progress_noise_content(content: str) -> bool:
    lines = split_terminal_lines(content)
    return bool(lines) and all(is_progress_noise_line(line) for line in lines)

