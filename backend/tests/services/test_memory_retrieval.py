from __future__ import annotations

from datetime import datetime, timedelta

from app.services.agent.memory.vector_store import VectorStoreService
from app.services.agent.prompts import builder as prompt_builder


class FakeEmbeddingService:
    def encode_single(self, text: str) -> list[float]:
        return [1.0]


class FakeMemoryCollection:
    def query(self, **kwargs):
        now = datetime.now()
        return {
            "ids": [["expired-1", "done-task", "resolved-error", "active-task"]],
            "documents": [
                [
                    "old deployment path",
                    "当前任务：已经完成的任务",
                    "已知错误：已经解决的错误",
                    "当前任务：修复 robot bridge",
                ]
            ],
            "metadatas": [
                [
                    {
                        "item_id": "item-1",
                        "memory_type": "fact",
                        "expires_at": (now - timedelta(days=1)).isoformat(),
                    },
                    {
                        "item_id": "item-1",
                        "memory_type": "task",
                        "status": "completed",
                    },
                    {
                        "item_id": "item-1",
                        "memory_type": "error",
                        "status": "resolved",
                    },
                    {
                        "item_id": "item-1",
                        "memory_type": "task",
                        "status": "active",
                    },
                ]
            ],
            "distances": [[0.1, 0.1, 0.1, 0.1]],
        }


def test_vector_memory_search_filters_expired_and_inactive_by_default() -> None:
    service = VectorStoreService()
    service._client = object()
    service._collection = FakeMemoryCollection()
    service._embedding_service = FakeEmbeddingService()

    try:
        results = service.search_memories(
            item_id="item-1",
            query="robot bridge task",
            n_results=5,
        )
    finally:
        service._client = None
        service._collection = None
        service._embedding_service = None

    assert [memory["id"] for memory in results] == ["active-task"]


def test_prompt_long_term_memory_recall_ranks_and_formats(monkeypatch) -> None:
    def fake_search_memories(*, memory_type: str, **_kwargs):
        memories_by_type = {
            "preference": [
                {
                    "id": "pref-1",
                    "content": "用户偏好：以后回复简洁中文",
                    "metadata": {
                        "memory_type": "preference",
                        "verified": True,
                        "updated_at": datetime.now().isoformat(),
                    },
                    "distance": 0.8,
                }
            ],
            "task": [
                {
                    "id": "task-1",
                    "content": "当前任务：修复 robot bridge 卡顿",
                    "metadata": {
                        "memory_type": "task",
                        "status": "active",
                    },
                    "distance": 0.2,
                },
                {
                    "id": "task-2",
                    "content": "当前任务：旧任务",
                    "metadata": {
                        "memory_type": "task",
                        "status": "completed",
                    },
                    "distance": 0.1,
                },
            ],
            "error": [
                {
                    "id": "error-1",
                    "content": "已知错误：旧错误",
                    "metadata": {
                        "memory_type": "error",
                        "status": "resolved",
                    },
                    "distance": 0.1,
                }
            ],
            "context": [
                {
                    "id": "context-1",
                    "content": "Robot bridge 通过 OneBot V11 WebSocket 接入 NapCat",
                    "metadata": {"memory_type": "context"},
                    "distance": 0.3,
                }
            ],
        }
        return memories_by_type.get(memory_type, [])

    monkeypatch.setattr(prompt_builder.vector_store, "search_memories", fake_search_memories)

    memories = prompt_builder._collect_long_term_memories(
        "item-1",
        "robot bridge 为什么卡顿",
        allowed_types=("preference", "task", "error", "context"),
        n_results=3,
    )

    assert "[task, active]" in memories
    assert "[preference, verified]" in memories
    assert "Robot bridge 通过 OneBot V11 WebSocket 接入 NapCat" in memories
    assert "旧任务" not in memories
    assert "旧错误" not in memories
