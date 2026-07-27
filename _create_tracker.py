# Create token usage tracker module
code = '''"""Lightweight in-memory token usage tracker per item."""
from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ModelUsage:
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    turns: int = 0


@dataclass
class ItemTokenStats:
    item_id: str
    models: dict[str, ModelUsage] = field(default_factory=dict)
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_turns: int = 0
    first_seen: str = ""
    last_seen: str = ""


class TokenUsageTracker:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, ItemTokenStats] = {}

    def record(
        self,
        item_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> None:
        now = datetime.now().isoformat(timespec="seconds")
        with self._lock:
            stats = self._items.get(item_id)
            if stats is None:
                stats = ItemTokenStats(item_id=item_id, first_seen=now)
                self._items[item_id] = stats
            stats.last_seen = now
            stats.total_prompt_tokens += prompt_tokens
            stats.total_completion_tokens += completion_tokens
            stats.total_tokens += total_tokens
            stats.total_turns += 1

            model_usage = stats.models.get(model)
            if model_usage is None:
                model_usage = ModelUsage(model=model)
                stats.models[model] = model_usage
            model_usage.prompt_tokens += prompt_tokens
            model_usage.completion_tokens += completion_tokens
            model_usage.total_tokens += total_tokens
            model_usage.turns += 1

    def get_item_stats(self, item_id: str) -> dict[str, Any] | None:
        with self._lock:
            stats = self._items.get(item_id)
            if stats is None:
                return None
            return {
                "item_id": stats.item_id,
                "total_prompt_tokens": stats.total_prompt_tokens,
                "total_completion_tokens": stats.total_completion_tokens,
                "total_tokens": stats.total_tokens,
                "total_turns": stats.total_turns,
                "first_seen": stats.first_seen,
                "last_seen": stats.last_seen,
                "models": [
                    {
                        "model": mu.model,
                        "prompt_tokens": mu.prompt_tokens,
                        "completion_tokens": mu.completion_tokens,
                        "total_tokens": mu.total_tokens,
                        "turns": mu.turns,
                    }
                    for mu in sorted(
                        stats.models.values(),
                        key=lambda x: x.total_tokens,
                        reverse=True,
                    )
                ],
            }

    def get_all_stats(self) -> list[dict[str, Any]]:
        with self._lock:
            result = []
            for stats in self._items.values():
                result.append({
                    "item_id": stats.item_id,
                    "total_prompt_tokens": stats.total_prompt_tokens,
                    "total_completion_tokens": stats.total_completion_tokens,
                    "total_tokens": stats.total_tokens,
                    "total_turns": stats.total_turns,
                    "first_seen": stats.first_seen,
                    "last_seen": stats.last_seen,
                    "models": [
                        {
                            "model": mu.model,
                            "prompt_tokens": mu.prompt_tokens,
                            "completion_tokens": mu.completion_tokens,
                            "total_tokens": mu.total_tokens,
                            "turns": mu.turns,
                        }
                        for mu in sorted(
                            stats.models.values(),
                            key=lambda x: x.total_tokens,
                            reverse=True,
                        )
                    ],
                })
            return result


token_usage_tracker = TokenUsageTracker()
'''

path = '/app/backend/app/services/agent/token_usage.py'
with open(path, 'w', encoding='utf-8') as f:
    f.write(code)
print("OK: created token_usage.py")
