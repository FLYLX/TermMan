from __future__ import annotations

from datetime import datetime, timedelta
from types import ModuleType, SimpleNamespace

import pytest

from app.services.agent.memory.vector_store import VectorStoreService
from app.services.agent.prompts import builder as prompt_builder
from app.services.agent.skills.definition import ActionConfig, SkillDefinition


class FakeEmbeddingService:
    def encode_single(self, text: str) -> list[float]:
        return [1.0]


class FailingEmbeddingService:
    def encode_single(self, text: str) -> list[float]:
        raise RuntimeError("embedding unavailable")


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


class FakeAddMemoryCollection:
    def __init__(self) -> None:
        self.add_calls: list[dict[str, object]] = []

    def add(self, **kwargs) -> None:
        self.add_calls.append(kwargs)


def test_embedding_service_does_not_import_model_by_default(monkeypatch) -> None:
    import sys

    from app.core.config import settings
    from app.services.agent.memory.vector_store import EmbeddingService

    calls: list[tuple[str, bool]] = []
    fake_module = ModuleType("sentence_transformers")

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, local_files_only: bool = False):
            calls.append((model_name, local_files_only))
            raise AssertionError("model should not be imported by default")

    fake_module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.setattr(settings, "EMBEDDING_ALLOW_REMOTE_LOAD", False)

    service = EmbeddingService()
    service._model = None
    service._load_error = None
    with pytest.raises(RuntimeError):
        service.encode_single("hello")
    assert calls == []

    with pytest.raises(RuntimeError):
        service.encode_single("hello again")
    assert calls == []

    service._load_error = None


def test_vector_add_memory_can_allow_manual_duplicates(monkeypatch, tmp_path) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "EMBEDDING_ALLOW_REMOTE_LOAD", True)
    service = VectorStoreService()
    collection = FakeAddMemoryCollection()
    service._client = object()
    service._collection = collection
    service._embedding_service = FakeEmbeddingService()

    def fail_duplicate_check(*_args, **_kwargs):
        raise AssertionError("manual duplicate writes should skip duplicate checks")

    monkeypatch.setattr(service, "_check_duplicate", fail_duplicate_check)

    memory_id = service.add_memory(
        item_id="item-1",
        content="same memory",
        memory_type="fact",
        allow_duplicate=True,
    )

    assert memory_id is not None
    assert collection.add_calls
    assert collection.add_calls[0]["documents"] == ["same memory"]


def test_vector_add_memory_saves_with_fallback_embedding_when_model_unavailable(
    monkeypatch,
    tmp_path,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIR", str(tmp_path))
    service = VectorStoreService()
    collection = FakeAddMemoryCollection()
    service._client = object()
    service._collection = collection
    service._embedding_service = FailingEmbeddingService()

    memory_id = service.add_memory(
        item_id="item-1",
        content="memory survives embedding failure",
        memory_type="fact",
        allow_duplicate=True,
    )

    assert memory_id is not None
    assert collection.add_calls == []
    memories = service.get_all_memories("item-1")
    assert [memory["content"] for memory in memories] == [
        "memory survives embedding failure"
    ]


def test_vector_memory_search_filters_expired_and_inactive_by_default(monkeypatch, tmp_path) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "EMBEDDING_ALLOW_REMOTE_LOAD", True)
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
    monkeypatch.setattr(prompt_builder.vector_store, "get_all_memories", lambda *_args, **_kwargs: [])

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


def test_preference_memories_are_always_included_without_query_match(monkeypatch) -> None:
    def fake_get_all_memories(*_args, memory_type: str, **_kwargs):
        if memory_type != "preference":
            return []
        return [
            {
                "id": "pref-persona",
                "content": "用户偏好：默认使用安静、简短的人格语气回复。",
                "metadata": {
                    "memory_type": "preference",
                    "verified": True,
                    "updated_at": datetime.now().isoformat(),
                },
            }
        ]

    def fake_search_memories(**_kwargs):
        return []

    monkeypatch.setattr(prompt_builder.vector_store, "get_all_memories", fake_get_all_memories)
    monkeypatch.setattr(prompt_builder.vector_store, "search_memories", fake_search_memories)

    memories = prompt_builder._collect_long_term_memories(
        "item-1",
        "说话",
        allowed_types=("fact", "preference", "task", "error", "context"),
        n_results=3,
    )

    assert "默认使用安静、简短的人格语气回复" in memories


def test_persona_skill_is_not_duplicated_as_regular_skill_prompt(monkeypatch) -> None:
    persona_skill = SkillDefinition(
        skill_id="quiet_persona",
        name="Quiet Persona",
        category="persona",
        action=ActionConfig(type="llm", prompt="Persona prompt should stay in system."),
    )

    agent = SimpleNamespace(
        get_skills=lambda: [persona_skill],
        match_skills=lambda _query: [persona_skill],
    )
    monkeypatch.setattr(prompt_builder, "get_system_prompt", lambda _agent: "Base system.")

    prompt = prompt_builder._build_skill_prompt(agent, "普通问题")

    assert "Base system." in prompt
    assert "Persona prompt should stay in system." not in prompt
