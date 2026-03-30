import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class EventType(Enum):
    NEEDS_ACTION = "needs_action"
    INFORMATIONAL = "informational"
    NOISE = "noise"


class ActionType(Enum):
    BLOCK = "block"
    IGNORE = "ignore"
    LOG = "log"
    REPLACE = "replace"


@dataclass
class FilterRule:
    name: str
    regex_patterns: list[str] = field(default_factory=list)
    action_type: str = "ignore"
    replace_rules: dict[str, str] = field(default_factory=dict)
    _compiled_patterns: list[re.Pattern] = field(default_factory=list, repr=False)

    def __post_init__(self):
        self._compiled_patterns = self._compile_patterns(self.regex_patterns)

    def _compile_patterns(self, patterns: list[str]) -> list[re.Pattern]:
        return [re.compile(p, re.IGNORECASE) for p in patterns]

    def matches(self, content: str) -> list[re.Match]:
        matches = []
        for pattern in self._compiled_patterns:
            matches.extend(pattern.finditer(content))
        return matches

    def apply_replace(self, content: str) -> str:
        if self.action_type != "replace":
            return content
        result = content
        for match_str, replace_str in self.replace_rules.items():
            try:
                result = re.sub(match_str, replace_str, result, flags=re.IGNORECASE)
            except re.error:
                pass
        return result


@dataclass
class InputFilterConfig:
    enabled: bool = False
    filters: list[FilterRule] = field(default_factory=list)

    @classmethod
    def from_item(cls, item: Any) -> "InputFilterConfig":
        rules = item.input_filter_rules or {}
        filters = []
        
        for filter_name, filter_config in rules.items():
            if isinstance(filter_config, dict):
                action = filter_config.get("action", {})
                filter_rule = FilterRule(
                    name=filter_name,
                    regex_patterns=filter_config.get("regex_patterns", []),
                    action_type=filter_config.get("action_type", "ignore"),
                    replace_rules=action.get("replace_rules", {}),
                )
                filters.append(filter_rule)
        
        return cls(
            enabled=item.input_filter_enabled,
            filters=filters,
        )


@dataclass
class FilteredEvent:
    raw_content: str
    event_type: EventType
    matches: list[dict[str, Any]]
    timestamp: datetime = field(default_factory=datetime.now)
    stdout: str = ""
    stderr: str = ""
    matched_filters: list[str] = field(default_factory=list)


class InputFilter:
    """
    Input Filter - Extract valuable information from terminal output

    Supports multiple independent filters, each with:
    - regex_patterns: list of patterns to match
    - action_type: "block" | "ignore" | "log" | "replace"
    - action.replace_rules: {match_pattern: replacement} (for replace type)
    """

    def __init__(self, config: InputFilterConfig):
        self.config = config
        self._last_content_hash: dict[str, int] = {}

    def filter(self, stream_data: dict[str, Any]) -> FilteredEvent | None:
        if not self.config.enabled:
            return self._create_event(stream_data, EventType.INFORMATIONAL)

        stdout = stream_data.get("stdout", "")
        stderr = stream_data.get("stderr", "")
        content = stdout + stderr

        if not content.strip():
            return None

        if self._is_duplicate(content):
            return None

        result = self._apply_filters(content)
        if result is None:
            return None

        event_type, cleaned_content, matched_filters, matches = result

        event = self._create_event(stream_data, event_type)
        event.raw_content = cleaned_content
        event.matched_filters = matched_filters
        event.matches = matches

        return event

    def _apply_filters(
        self, content: str
    ) -> tuple[EventType, str, list[str], list[dict[str, Any]]] | None:
        cleaned_content = content
        matched_filters: list[str] = []
        all_matches: list[dict[str, Any]] = []
        has_block = False
        has_log = False

        for filter_rule in self.config.filters:
            matches = filter_rule.matches(cleaned_content)
            
            if not matches:
                continue

            matched_filters.append(filter_rule.name)
            
            for match in matches:
                all_matches.append({
                    "filter": filter_rule.name,
                    "pattern": match.re.pattern,
                    "matched": match.group(),
                    "action_type": filter_rule.action_type,
                })

            if filter_rule.action_type == "block":
                has_block = True
                
            elif filter_rule.action_type == "ignore":
                for pattern in filter_rule._compiled_patterns:
                    cleaned_content = pattern.sub("", cleaned_content)
                
            elif filter_rule.action_type == "log":
                has_log = True
                
            elif filter_rule.action_type == "replace":
                cleaned_content = filter_rule.apply_replace(cleaned_content)

        if has_block:
            return None

        if has_log:
            event_type = EventType.NEEDS_ACTION
        else:
            event_type = EventType.INFORMATIONAL

        return event_type, cleaned_content, matched_filters, all_matches

    def _is_duplicate(self, content: str) -> bool:
        content_hash = hash(content.strip())
        item_key = "default"

        if item_key in self._last_content_hash:
            if self._last_content_hash[item_key] == content_hash:
                return True

        self._last_content_hash[item_key] = content_hash
        return False

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
