import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any
from datetime import datetime
from collections import defaultdict
import time


class FilterAction(Enum):
    ALLOWED = "allowed"
    BLOCKED = "blocked"
    MODIFIED = "modified"
    NEEDS_APPROVAL = "needs_approval"


@dataclass
class OutputFilterConfig:
    enabled: bool = False
    mode: str = "blacklist"
    command_list: list[str] = field(default_factory=list)
    sensitive_patterns: list[str] = field(default_factory=list)
    rate_limit: int = 10

    @classmethod
    def from_item(cls, item: Any) -> "OutputFilterConfig":
        return cls(
            enabled=item.output_filter_enabled,
            mode=item.output_filter_mode,
            command_list=item.output_command_list or [],
            sensitive_patterns=item.output_sensitive_patterns or [],
            rate_limit=item.output_rate_limit,
        )


@dataclass
class FilterResult:
    action: FilterAction
    command: str
    reason: str = ""
    original_command: str = ""

    @property
    def is_allowed(self) -> bool:
        return self.action == FilterAction.ALLOWED

    @property
    def is_blocked(self) -> bool:
        return self.action == FilterAction.BLOCKED

    @property
    def needs_approval(self) -> bool:
        return self.action == FilterAction.NEEDS_APPROVAL


class RiskLevel(Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


DEFAULT_BLACKLIST = [
    r"rm\s+-rf\s+/",
    r"rm\s+-rf\s+~",
    r"mkfs",
    r"dd\s+if=",
    r">\s*/dev/sd",
    r":\(\)\s*\{\s*:\|\:&\s*\}\s*;:",
    r"chmod\s+777\s+/",
    r"chown\s+.*:.*\s+/",
    r"shutdown",
    r"reboot",
    r"init\s+0",
    r"init\s+6",
    r"halt",
    r"poweroff",
]

DEFAULT_WHITELIST = [
    r"^ls\b",
    r"^cat\b",
    r"^grep\b",
    r"^find\b",
    r"^ps\b",
    r"^top\b",
    r"^pwd\b",
    r"^echo\b",
    r"^whoami\b",
    r"^date\b",
    r"^git\s+status\b",
    r"^git\s+log\b",
    r"^git\s+diff\b",
    r"^git\s+branch\b",
]

DEFAULT_SENSITIVE_PATTERNS = [
    r"password\s*=\s*\S+",
    r"api[_-]?key\s*=\s*\S+",
    r"secret\s*=\s*\S+",
    r"token\s*=\s*\S+",
    r"--password\s+\S+",
    r"-p\s+\S+",
]


class OutputFilter:
    """
    输出过滤器 - 安全检查Agent生成的命令

    过滤策略:
    1. RateLimiter: 频率限制 (防止命令风暴)
    2. SensitiveDataFilter: 敏感数据过滤
    3. CommandFilter: 命令过滤 (黑名单/白名单)
    4. SafetyChecker: 安全检查 (危险操作检测)
    """

    def __init__(self, config: OutputFilterConfig):
        self.config = config
        self._blacklist = self._compile_patterns(DEFAULT_BLACKLIST)
        self._whitelist = self._compile_patterns(DEFAULT_WHITELIST)
        self._sensitive_patterns = self._compile_sensitive_patterns()
        self._rate_tracker: dict[str, list[float]] = defaultdict(list)

    def _compile_patterns(self, patterns: list[str]) -> list[re.Pattern]:
        compiled = [re.compile(p, re.IGNORECASE) for p in patterns]
        if self.config.mode == "blacklist" and self.config.command_list:
            compiled.extend(re.compile(p, re.IGNORECASE) for p in self.config.command_list)
        return compiled

    def _compile_sensitive_patterns(self) -> list[re.Pattern]:
        patterns = list(DEFAULT_SENSITIVE_PATTERNS)
        if self.config.sensitive_patterns:
            patterns.extend(self.config.sensitive_patterns)
        return [re.compile(p, re.IGNORECASE) for p in patterns]

    def filter(self, command: str, item_uuid: str = "default") -> FilterResult:
        if not self.config.enabled:
            return FilterResult(
                action=FilterAction.ALLOWED,
                command=command,
                original_command=command,
            )

        if not self._check_rate_limit(item_uuid):
            return FilterResult(
                action=FilterAction.BLOCKED,
                command=command,
                reason=f"Rate limit exceeded ({self.config.rate_limit}/min)",
                original_command=command,
            )

        if self._contains_sensitive_data(command):
            return FilterResult(
                action=FilterAction.BLOCKED,
                command=command,
                reason="Command contains sensitive data patterns",
                original_command=command,
            )

        if self.config.mode == "blacklist":
            result = self._check_blacklist(command)
            if result:
                return result
        else:
            result = self._check_whitelist(command)
            if result:
                return result

        risk = self._assess_risk(command)
        if risk == RiskLevel.HIGH:
            return FilterResult(
                action=FilterAction.NEEDS_APPROVAL,
                command=command,
                reason="High risk command requires approval",
                original_command=command,
            )

        if risk == RiskLevel.CRITICAL:
            return FilterResult(
                action=FilterAction.BLOCKED,
                command=command,
                reason="Critical risk command is blocked",
                original_command=command,
            )

        modified = self._modify_if_needed(command)
        if modified != command:
            return FilterResult(
                action=FilterAction.MODIFIED,
                command=modified,
                reason="Command modified for safety",
                original_command=command,
            )

        return FilterResult(
            action=FilterAction.ALLOWED,
            command=command,
            original_command=command,
        )

    def _check_rate_limit(self, item_uuid: str) -> bool:
        now = time.time()
        minute_ago = now - 60

        self._rate_tracker[item_uuid] = [
            t for t in self._rate_tracker[item_uuid] if t > minute_ago
        ]

        if len(self._rate_tracker[item_uuid]) >= self.config.rate_limit:
            return False

        self._rate_tracker[item_uuid].append(now)
        return True

    def _contains_sensitive_data(self, command: str) -> bool:
        for pattern in self._sensitive_patterns:
            if pattern.search(command):
                return True
        return False

    def _check_blacklist(self, command: str) -> FilterResult | None:
        for pattern in self._blacklist:
            if pattern.search(command):
                return FilterResult(
                    action=FilterAction.BLOCKED,
                    command=command,
                    reason=f"Command matches blacklist pattern: {pattern.pattern}",
                    original_command=command,
                )
        return None

    def _check_whitelist(self, command: str) -> FilterResult | None:
        for pattern in self._whitelist:
            if pattern.search(command):
                return None

        if self.config.command_list:
            for custom_pattern in self.config.command_list:
                if re.search(custom_pattern, command, re.IGNORECASE):
                    return None

        return FilterResult(
            action=FilterAction.BLOCKED,
            command=command,
            reason="Command not in whitelist",
            original_command=command,
        )

    def _assess_risk(self, command: str) -> RiskLevel:
        critical_patterns = [
            r"rm\s+-rf",
            r"format",
            r"del\s+/",
            r"drop\s+table",
            r"truncate",
        ]

        high_risk_patterns = [
            r"sudo\s+",
            r"su\s+",
            r"chmod\s+",
            r"chown\s+",
            r"kill\s+-9",
            r"pkill",
            r"iptables",
            r"ufw",
        ]

        medium_risk_patterns = [
            r"apt\s+",
            r"yum\s+",
            r"pip\s+install",
            r"npm\s+install",
            r"curl\s+",
            r"wget\s+",
            r"git\s+push",
            r"git\s+reset",
        ]

        for pattern in critical_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return RiskLevel.CRITICAL

        for pattern in high_risk_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return RiskLevel.HIGH

        for pattern in medium_risk_patterns:
            if re.search(pattern, command, re.IGNORECASE):
                return RiskLevel.MEDIUM

        return RiskLevel.LOW

    def _modify_if_needed(self, command: str) -> str:
        if command.strip().endswith("\n"):
            return command

        if not command.strip().endswith("\n"):
            return command.rstrip() + "\n"

        return command
