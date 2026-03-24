import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class EventType(Enum):
    NEEDS_ACTION = "needs_action"
    INFORMATIONAL = "informational"
    NOISE = "noise"


@dataclass
class InputFilterConfig:
    enabled: bool = False
    mode: str = "blacklist"
    noise_patterns: list[str] = field(default_factory=list)
    event_patterns: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_item(cls, item: Any) -> "InputFilterConfig":
        return cls(
            enabled=item.input_filter_enabled,
            mode=item.input_filter_mode,
            noise_patterns=item.input_noise_patterns or [],
            event_patterns=item.input_event_patterns or {},
        )


@dataclass
class FilteredEvent:
    raw_content: str
    event_type: EventType
    matches: list[re.Match]
    timestamp: datetime = field(default_factory=datetime.now)
    stdout: str = ""
    stderr: str = ""


class InputFilter:
    """
    输入过滤器 - 从终端输出中提取有价值信息

    过滤策略:
    1. NoiseReducer: 降低噪音 (重复行、进度条等)
    2. PatternMatcher: 匹配关键模式 (错误、警告、提示符等)
    3. EventClassifier: 分类事件类型 (需要Action/仅记录/忽略)
    """

    DEFAULT_EVENT_PATTERNS = {
        "error": [r"error:", r"failed:", r"exception:", r"Error:", r"FAILED", r"EXCEPTION"],
        "warning": [r"warning:", r"warn:", r"Warning:", r"WARN"],
        "prompt": [r"\$\s*$", r"#\s*$", r">>>\s*$", r">\s*$"],
        "progress": [r"\d+%", r"\[\s*=+\s*\]", r"\.\.\.+"],
        "input_required": [r"\(y/n\)", r"\[Y/n\]", r"enter.*:", r"password:", r"confirm"],
    }

    DEFAULT_NOISE_PATTERNS = [
        r"^\s*$",
        r"^\x1b\[[0-9;]*[a-zA-Z]$",
        r"^\r$",
    ]

    def __init__(self, config: InputFilterConfig):
        self.config = config
        self._noise_patterns = self._compile_noise_patterns()
        self._event_patterns = self._compile_event_patterns()
        self._last_content_hash: dict[str, int] = {}

    def _compile_noise_patterns(self) -> list[re.Pattern]:
        patterns = list(self.DEFAULT_NOISE_PATTERNS)
        if self.config.noise_patterns:
            patterns.extend(self.config.noise_patterns)
        return [re.compile(p) for p in patterns]

    def _compile_event_patterns(self) -> dict[str, list[re.Pattern]]:
        event_patterns = dict(self.DEFAULT_EVENT_PATTERNS)
        if self.config.event_patterns:
            event_patterns.update(self.config.event_patterns)

        compiled = {}
        for event_type, patterns in event_patterns.items():
            compiled[event_type] = [re.compile(p, re.IGNORECASE) for p in patterns]
        return compiled

    def filter(self, stream_data: dict[str, Any]) -> FilteredEvent | None:
        if not self.config.enabled:
            return self._create_event(stream_data, EventType.INFORMATIONAL)

        stdout = stream_data.get("stdout", "")
        stderr = stream_data.get("stderr", "")
        content = stdout + stderr

        if not content.strip():
            return None

        cleaned = self._reduce_noise(content)
        if not cleaned:
            return None

        if self._is_duplicate(cleaned):
            return None

        matches = self._match_patterns(cleaned)
        event_type = self._classify_event(cleaned, matches)

        event = self._create_event(stream_data, event_type)
        event.raw_content = cleaned
        event.matches = matches

        return event

    def _reduce_noise(self, content: str) -> str:
        lines = content.split("\n")
        cleaned_lines = []

        for line in lines:
            is_noise = False
            for pattern in self._noise_patterns:
                if pattern.match(line):
                    is_noise = True
                    break

            if not is_noise and line.strip():
                cleaned_lines.append(line)

        return "\n".join(cleaned_lines)

    def _is_duplicate(self, content: str) -> bool:
        content_hash = hash(content.strip())
        item_key = "default"

        if item_key in self._last_content_hash:
            if self._last_content_hash[item_key] == content_hash:
                return True

        self._last_content_hash[item_key] = content_hash
        return False

    def _match_patterns(self, content: str) -> list[re.Match]:
        matches = []
        for event_type, patterns in self._event_patterns.items():
            for pattern in patterns:
                for match in pattern.finditer(content):
                    matches.append(match)
        return matches

    def _classify_event(self, content: str, matches: list[re.Match]) -> EventType:
        if not matches:
            return EventType.INFORMATIONAL

        match_types = set()
        for match in matches:
            for event_type, patterns in self._event_patterns.items():
                for pattern in patterns:
                    if pattern.search(content):
                        match_types.add(event_type)
                        break

        if "input_required" in match_types:
            return EventType.NEEDS_ACTION
        if "error" in match_types:
            return EventType.NEEDS_ACTION
        if "warning" in match_types:
            return EventType.INFORMATIONAL
        if "progress" in match_types:
            return EventType.NOISE

        return EventType.INFORMATIONAL

    def _create_event(
        self, stream_data: dict[str, Any], event_type: EventType
    ) -> FilteredEvent:
        return FilteredEvent(
            raw_content=stream_data.get("stdout", "") + stream_data.get("stderr", ""),
            event_type=event_type,
            matches=[],
            stdout=stream_data.get("stdout", ""),
            stderr=stream_data.get("stderr", ""),
        )
