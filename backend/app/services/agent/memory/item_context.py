from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class Interaction:
    timestamp: datetime = field(default_factory=datetime.now)
    user_input: str = ""
    agent_response: str = ""
    command_executed: str | None = None
    result: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ItemContext:
    item_uuid: str
    working_directory: str | None = None
    environment: dict[str, str] = field(default_factory=dict)
    last_command: str | None = None
    last_exit_code: int | None = None
    custom_data: dict[str, Any] = field(default_factory=dict)

    def update(self, **kwargs):
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "item_uuid": self.item_uuid,
            "working_directory": self.working_directory,
            "environment": self.environment,
            "last_command": self.last_command,
            "last_exit_code": self.last_exit_code,
            "custom_data": self.custom_data,
        }
