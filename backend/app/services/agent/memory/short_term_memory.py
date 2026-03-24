from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .item_context import Interaction


@dataclass
class ShortTermMemory:
    """
    短期记忆 - 使用环形缓冲区存储最近交互

    特点:
    - 会话级记忆，不持久化
    - 固定容量，自动淘汰最旧记录
    - 快速访问最近交互
    """

    max_entries: int = 100
    _buffer: dict[str, deque] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        object.__setattr__(self, "_buffer", {})

    def add(self, item_uuid: str, interaction: Interaction):
        if item_uuid not in self._buffer:
            self._buffer[item_uuid] = deque(maxlen=self.max_entries)
        self._buffer[item_uuid].append(interaction)

    def get_recent(self, item_uuid: str, limit: int = 10) -> list[Interaction]:
        if item_uuid not in self._buffer:
            return []
        return list(self._buffer[item_uuid])[-limit:]

    def get_all(self, item_uuid: str) -> list[Interaction]:
        if item_uuid not in self._buffer:
            return []
        return list(self._buffer[item_uuid])

    def clear(self, item_uuid: str | None = None):
        if item_uuid:
            if item_uuid in self._buffer:
                del self._buffer[item_uuid]
        else:
            self._buffer.clear()

    def get_count(self, item_uuid: str) -> int:
        return len(self._buffer.get(item_uuid, []))

    def search(self, item_uuid: str, query: str) -> list[Interaction]:
        results = []
        for interaction in self.get_all(item_uuid):
            if (
                query.lower() in interaction.user_input.lower()
                or query.lower() in interaction.agent_response.lower()
                or (interaction.command_executed and query.lower() in interaction.command_executed.lower())
            ):
                results.append(interaction)
        return results

    def to_context_string(self, item_uuid: str, limit: int = 10) -> str:
        interactions = self.get_recent(item_uuid, limit)
        if not interactions:
            return ""

        lines = []
        for i, interaction in enumerate(interactions, 1):
            lines.append(f"[{i}] User: {interaction.user_input}")
            if interaction.agent_response:
                lines.append(f"[{i}] Agent: {interaction.agent_response}")
            if interaction.command_executed:
                lines.append(f"[{i}] Command: {interaction.command_executed}")

        return "\n".join(lines)
