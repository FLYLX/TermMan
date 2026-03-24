import logging
from dataclasses import dataclass, field
from typing import Any

from .short_term_memory import ShortTermMemory
from .item_context import ItemContext, Interaction

logger = logging.getLogger(__name__)


@dataclass
class MemoryManager:
    """
    记忆管理器 - 管理 Agent 的记忆系统

    记忆类型:
    1. ShortTermMemory: 短期记忆 (最近N条交互，会话级)
    2. ItemContext: Item 特定上下文 (工作目录、环境变量等)
    """

    handler_id: str
    max_short_term_entries: int = 100
    _short_term: ShortTermMemory = field(init=False, repr=False)
    _item_contexts: dict[str, ItemContext] = field(default_factory=dict, repr=False)

    def __post_init__(self):
        self._short_term = ShortTermMemory(max_entries=self.max_short_term_entries)

    def add_interaction(self, item_uuid: str, interaction: Interaction):
        self._short_term.add(item_uuid, interaction)

    def get_recent_interactions(self, item_uuid: str, limit: int = 10) -> list[Interaction]:
        return self._short_term.get_recent(item_uuid, limit)

    def get_context(self, item_uuid: str) -> ItemContext:
        if item_uuid not in self._item_contexts:
            self._item_contexts[item_uuid] = ItemContext(item_uuid=item_uuid)
        return self._item_contexts[item_uuid]

    def update_context(self, item_uuid: str, **kwargs):
        context = self.get_context(item_uuid)
        context.update(**kwargs)

    def get_relevant_context(self, item_uuid: str, query: str | None = None) -> str:
        recent = self._short_term.to_context_string(item_uuid, limit=10)
        context = self._item_contexts.get(item_uuid)

        parts = []

        if context:
            parts.append(f"Working Directory: {context.working_directory or 'unknown'}")
            if context.last_command:
                parts.append(f"Last Command: {context.last_command}")
            if context.last_exit_code is not None:
                parts.append(f"Last Exit Code: {context.last_exit_code}")

        if recent:
            parts.append(f"\nRecent Interactions:\n{recent}")

        return "\n".join(parts)

    def clear_item_memory(self, item_uuid: str):
        self._short_term.clear(item_uuid)
        if item_uuid in self._item_contexts:
            del self._item_contexts[item_uuid]

    def clear_all(self):
        self._short_term.clear()
        self._item_contexts.clear()

    def get_stats(self, item_uuid: str) -> dict[str, Any]:
        return {
            "handler_id": self.handler_id,
            "item_uuid": item_uuid,
            "interaction_count": self._short_term.get_count(item_uuid),
            "has_context": item_uuid in self._item_contexts,
        }

    def record_command(
        self,
        item_uuid: str,
        command: str,
        result: str | None = None,
        exit_code: int | None = None,
    ):
        interaction = Interaction(
            command_executed=command,
            result=result,
        )

        self.add_interaction(item_uuid, interaction)
        self.update_context(
            item_uuid,
            last_command=command,
            last_exit_code=exit_code,
        )

    def record_exchange(
        self,
        item_uuid: str,
        user_input: str,
        agent_response: str,
        command: str | None = None,
    ):
        interaction = Interaction(
            user_input=user_input,
            agent_response=agent_response,
            command_executed=command,
        )
        self.add_interaction(item_uuid, interaction)
