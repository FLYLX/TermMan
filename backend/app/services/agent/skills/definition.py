from dataclasses import dataclass, field
from typing import Any


@dataclass
class TriggerConfig:
    type: str = "manual"
    patterns: list[str] = field(default_factory=list)
    interval: int | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TriggerConfig":
        return cls(
            type=data.get("type", "manual"),
            patterns=data.get("patterns", []),
            interval=data.get("interval"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "patterns": self.patterns,
            "interval": self.interval,
        }


@dataclass
class ActionConfig:
    type: str = "llm"
    prompt: str | None = None
    command: str | None = None
    script: str | None = None
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ActionConfig":
        return cls(
            type=data.get("type", "llm"),
            prompt=data.get("prompt"),
            command=data.get("command"),
            script=data.get("script"),
            params=data.get("params", {}),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "prompt": self.prompt,
            "command": self.command,
            "script": self.script,
            "params": self.params,
        }


@dataclass
class SafetyConfig:
    requires_approval: bool = False
    risk_level: str = "low"
    max_retries: int = 3
    timeout: int = 60

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SafetyConfig":
        return cls(
            requires_approval=data.get("requires_approval", False),
            risk_level=data.get("risk_level", "low"),
            max_retries=data.get("max_retries", 3),
            timeout=data.get("timeout", 60),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "requires_approval": self.requires_approval,
            "risk_level": self.risk_level,
            "max_retries": self.max_retries,
            "timeout": self.timeout,
        }


@dataclass
class SkillDefinition:
    skill_id: str
    name: str
    description: str = ""
    category: str = "general"
    trigger: TriggerConfig = field(default_factory=TriggerConfig)
    action: ActionConfig = field(default_factory=ActionConfig)
    safety: SafetyConfig = field(default_factory=SafetyConfig)
    content: str = ""
    scripts: dict[str, str] = field(default_factory=dict)
    templates: dict[str, str] = field(default_factory=dict)
    resources: dict[str, bytes] = field(default_factory=dict)
    examples: list[dict[str, Any]] = field(default_factory=list)
    mcp_servers: list[str] = field(default_factory=list)
    skill_dir: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "trigger": self.trigger.to_dict(),
            "action": self.action.to_dict(),
            "safety": self.safety.to_dict(),
            "content": self.content,
            "mcp_servers": self.mcp_servers,
        }
