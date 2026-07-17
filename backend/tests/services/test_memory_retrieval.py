from __future__ import annotations

import importlib
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


class FakeMigrationEmbeddingService:
    def encode(self, texts: str | list[str]) -> list[list[float]]:
        if isinstance(texts, str):
            texts = [texts]
        return [[1.0, *([0.0] * 511)] for _text in texts]

    def encode_single(self, text: str) -> list[float]:
        return self.encode(text)[0]

    def dimension(self) -> int:
        return 512


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


def test_embedding_service_uses_local_cache_without_remote_fallback(monkeypatch) -> None:
    import sys

    from app.core.config import settings
    from app.services.agent.memory.vector_store import EmbeddingService

    calls: list[tuple[str, bool]] = []
    fake_module = ModuleType("sentence_transformers")

    class FakeSentenceTransformer:
        def __init__(self, model_name: str, local_files_only: bool = False):
            calls.append((model_name, local_files_only))
            raise RuntimeError("local cache missing")

    fake_module.SentenceTransformer = FakeSentenceTransformer
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_module)
    monkeypatch.setattr(settings, "EMBEDDING_ALLOW_REMOTE_LOAD", False)

    service = EmbeddingService()
    service._model = None
    service._model_name = None
    service._load_error = None
    with pytest.raises(RuntimeError):
        service.encode_single("hello")
    assert calls == [("BAAI/bge-small-zh-v1.5", True)]

    with pytest.raises(RuntimeError):
        service.encode_single("hello again")
    assert calls == [("BAAI/bge-small-zh-v1.5", True)]

    service._load_error = None
    service._model_name = None


def test_vector_store_opens_chroma_when_remote_model_loading_is_disabled(
    monkeypatch,
    tmp_path,
) -> None:
    from app.core.config import settings

    vector_store_module = importlib.import_module(
        "app.services.agent.memory.vector_store"
    )

    collection = object()

    class FakeClient:
        def get_or_create_collection(self, **kwargs):
            assert kwargs["name"] == "item_memories"
            return collection

    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "EMBEDDING_ALLOW_REMOTE_LOAD", False)
    monkeypatch.setattr(
        vector_store_module.chromadb,
        "PersistentClient",
        lambda *, path: FakeClient(),
    )
    service = VectorStoreService()
    service._client = None
    service._collection = None
    service._embedding_service = None

    try:
        service._ensure_initialized()
        assert service._collection is collection
    finally:
        service._client = None
        service._collection = None
        service._embedding_service = None


def test_vector_store_reindexes_existing_memories_when_model_changes(
    monkeypatch,
    tmp_path,
) -> None:
    from app.core.config import settings

    vector_store_module = importlib.import_module(
        "app.services.agent.memory.vector_store"
    )
    client = vector_store_module.chromadb.PersistentClient(path=str(tmp_path))
    legacy = client.get_or_create_collection(
        name="item_memories",
        metadata={"description": "Long-term memory for items"},
    )
    legacy.add(
        ids=["memory-1"],
        embeddings=[[1.0, *([0.0] * 383)]],
        documents=["用户希望被叫主人"],
        metadatas=[{"item_id": "item-1", "memory_type": "preference"}],
    )

    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIR", str(tmp_path))
    monkeypatch.setattr(settings, "EMBEDDING_MODEL_NAME", "BAAI/bge-small-zh-v1.5")
    monkeypatch.setattr(
        vector_store_module,
        "EmbeddingService",
        lambda: FakeMigrationEmbeddingService(),
    )
    service = VectorStoreService()
    service._client = None
    service._collection = None
    service._embedding_service = None
    service._collection_embedding_model = None

    try:
        service._ensure_initialized()

        assert service._collection is not None
        assert service._collection.name.startswith("item_memories_baai_bge_small_zh")
        assert service._collection.count() == 1
        assert service._collection.metadata["embedding_model"] == "BAAI/bge-small-zh-v1.5"
        assert service._collection.metadata["embedding_dimension"] == 512
        assert service.get_all_memories("item-1")[0]["id"] == "memory-1"

        assert [
            collection.name
            for collection in service._client.list_collections()
            if collection.name.startswith("item_memories")
        ] == [service._collection.name]
    finally:
        service._client = None
        service._collection = None
        service._embedding_service = None
        service._collection_embedding_model = None


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


def test_hybrid_search_uses_fts_for_exact_technical_values(
    monkeypatch,
    tmp_path,
) -> None:
    from app.core.config import settings

    class SemanticCollection:
        def query(self, **_kwargs):
            return {
                "ids": [["semantic-only"]],
                "documents": [["Minecraft server is configured"]],
                "metadatas": [[{"item_id": "item-1", "memory_type": "fact"}]],
                "distances": [[0.45]],
            }

    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIR", str(tmp_path))
    service = VectorStoreService()
    service._client = object()
    service._collection = SemanticCollection()
    service._embedding_service = FakeEmbeddingService()
    service._collection_embedding_model = None
    service._lexical_index_path = None
    service._lexical_index_available = True
    monkeypatch.setattr(service, "maintain_memories", lambda *_args, **_kwargs: {})
    service._upsert_lexical_memory(
        memory_id="exact-port",
        content="Minecraft 服务端口是 43906",
        metadata={"item_id": "item-1", "memory_type": "fact"},
    )

    try:
        results = service.search_memories(
            item_id="item-1",
            query="43906",
            n_results=1,
        )
    finally:
        service._client = None
        service._collection = None
        service._embedding_service = None
        service._collection_embedding_model = None
        service._lexical_index_path = None

    assert [memory["id"] for memory in results] == ["exact-port"]


def test_preference_and_error_memories_are_permanent(monkeypatch, tmp_path) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIR", str(tmp_path))
    service = VectorStoreService()
    service._client = object()
    service._collection = None
    service._embedding_service = FailingEmbeddingService()

    try:
        service.add_memory(
            item_id="item-permanent",
            content="reply in Chinese",
            memory_type="preference",
            ttl_days=1,
            allow_duplicate=True,
            run_maintenance=False,
        )
        service.add_memory(
            item_id="item-permanent",
            content="known startup error and solution",
            memory_type="error",
            ttl_days=1,
            allow_duplicate=True,
            run_maintenance=False,
        )
        service.add_memory(
            item_id="item-permanent",
            content="server port is 43906",
            memory_type="fact",
            ttl_days=1,
            allow_duplicate=True,
            run_maintenance=False,
        )

        memories = service.get_all_memories("item-permanent")
        metadata_by_type = {
            memory["metadata"]["memory_type"]: memory["metadata"]
            for memory in memories
        }
        assert "expires_at" not in metadata_by_type["preference"]
        assert "expires_at" not in metadata_by_type["error"]
        assert metadata_by_type["fact"]["expires_at"]
    finally:
        service._client = None
        service._collection = None
        service._embedding_service = None


def test_compacts_ten_expired_memories_into_one_scoped_summary(
    monkeypatch,
    tmp_path,
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIR", str(tmp_path))
    service = VectorStoreService()
    service._client = object()
    service._collection = None
    service._embedding_service = FailingEmbeddingService()
    expired_at = (datetime.now() - timedelta(days=1)).isoformat()

    for index in range(10):
        service._upsert_fallback_memory(
            memory_id=f"expired-{index}",
            content=f"historical server fact {index}",
            metadata={
                "item_id": "item-expired",
                "memory_type": "fact",
                "memory_scope": "conversation",
                "robot_id": "robot-1",
                "robot_conversation_key": "group:100",
                "expires_at": expired_at,
                "created_at": f"2026-01-{index + 1:02d}T00:00:00",
            },
        )

    try:
        result = service.compact_expired_memories("item-expired", threshold=10)
        memories = service.get_all_memories("item-expired")

        assert result["summarized"] == 10
        assert result["summaries_created"] == 1
        assert len(memories) == 1
        assert memories[0]["content"].startswith("历史事实记忆摘要：")
        assert memories[0]["metadata"]["compressed_count"] == 10
        assert memories[0]["metadata"]["robot_conversation_key"] == "group:100"
        assert memories[0]["metadata"]["expires_at"]
    finally:
        service._client = None
        service._collection = None
        service._embedding_service = None
        service._maintenance_items.discard("item-expired")
        service._maintenance_last_checked.pop("item-expired", None)


def test_vector_store_rejects_removed_task_memory_type(monkeypatch, tmp_path) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIR", str(tmp_path))
    service = VectorStoreService()
    service._client = object()
    service._collection = None
    service._embedding_service = FailingEmbeddingService()

    try:
        with pytest.raises(ValueError, match="Unsupported long-term memory type"):
            service.add_memory(
                item_id="item-task",
                content="install Java",
                memory_type="task",  # type: ignore[arg-type]
                allow_duplicate=True,
                run_maintenance=False,
            )
    finally:
        service._client = None
        service._collection = None
        service._embedding_service = None


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

    assert [memory["id"] for memory in results] == ["resolved-error"]


def test_prompt_long_term_memory_recall_ranks_and_formats(monkeypatch) -> None:
    monkeypatch.setattr(prompt_builder.vector_store, "get_all_memories", lambda *_args, **_kwargs: [])
    search_calls: list[str | None] = []

    def fake_search_memories(*, memory_type: str | None = None, **_kwargs):
        search_calls.append(memory_type)
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
                    "distance": 0.4,
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
                    "distance": 0.6,
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
        if memory_type is not None:
            return memories_by_type.get(memory_type, [])
        return [
            memory
            for current_type, typed_memories in memories_by_type.items()
            if current_type != "task"
            for memory in typed_memories
        ]

    monkeypatch.setattr(prompt_builder.vector_store, "search_memories", fake_search_memories)

    memories = prompt_builder._collect_long_term_memories(
        "item-1",
        "robot bridge 为什么卡顿",
        allowed_types=("preference", "error", "context"),
        n_results=3,
    )

    assert "- 用户偏好：以后回复简洁中文" in memories
    assert "- Robot bridge 通过 OneBot V11 WebSocket 接入 NapCat" in memories
    assert "已知错误：旧错误" not in memories
    assert "旧任务" not in memories
    assert "verified" not in memories
    assert search_calls == [None]


def test_progressive_history_expands_only_for_referential_messages() -> None:
    assert prompt_builder._recent_context_limit("请检查服务端口", 10) == 4
    assert prompt_builder._recent_context_limit("刚才那个怎么样了", 10) == 10


def test_referential_memory_query_uses_two_recent_conversation_messages() -> None:
    query = prompt_builder._build_memory_retrieval_query(
        "那个端口是多少",
        [
            {"role": "user", "content": "帮我检查 Minecraft 服务端"},
            {"role": "assistant", "content": "服务器已经启动，正在检查配置"},
            {"role": "user", "content": "它使用了自定义端口"},
        ],
    )

    assert query.startswith("那个端口是多少")
    assert "服务器已经启动" in query
    assert "自定义端口" in query


def test_long_term_memory_prompt_keeps_sender_and_content_only() -> None:
    formatted = prompt_builder._format_long_term_memory(
        {
            "id": "internal-memory-id",
            "content": '问"你怎么看的"是在问查看方法，不是在问观点',
            "metadata": {
                "memory_type": "preference",
                "speaker": "Ac国常务腐管理（2537134688）",
                "created_at": "2026-07-06T12:04:24.279188",
                "expires_at": "2026-08-05T12:04:24.279188",
                "imported_from_memory_id": "legacy-memory-id",
            },
        }
    )

    assert formatted == (
        '- Ac国常务腐管理（2537134688）: 问"你怎么看的"是在问查看方法，不是在问观点'
    )
    assert "2026-" not in formatted
    assert "memory-id" not in formatted


def test_preference_memories_are_always_included_without_query_match(monkeypatch) -> None:
    def fake_get_all_memories(*_args, memory_type: str | None = None, **_kwargs):
        if memory_type not in {None, "preference"}:
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


def test_verified_recent_fact_memories_are_always_included_without_query_match(monkeypatch) -> None:
    def fake_get_all_memories(*_args, memory_type: str | None = None, **_kwargs):
        if memory_type not in {None, "fact"}:
            return []
        return [
            {
                "id": "fact-identity",
                "content": "你叫大狗",
                "metadata": {
                    "memory_type": "fact",
                    "type": "agent_saved",
                    "source": "local_agent_saved",
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
        "你是谁",
        allowed_types=("fact", "preference", "task", "error", "context"),
        n_results=3,
    )

    assert "你叫大狗" in memories


def test_robot_scoped_always_on_memory_does_not_cross_conversations(monkeypatch) -> None:
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="robot-1",
            robot_conversation_key="group:g1",
            robot_sender_key="onebot_v11:group:g1:u1",
        )
    )

    def fake_get_all_memories(*_args, memory_type: str | None = None, **_kwargs):
        if memory_type not in {None, "context"}:
            return []
        return [
            {
                "id": "ctx-g1",
                "content": "这个群正在开 Forge 服务器",
                "metadata": {
                    "memory_type": "context",
                    "source": "qq_robot_auto_promoted",
                    "robot_id": "robot-1",
                    "conversation_key": "group:g1",
                    "robot_conversation_key": "group:g1",
                    "memory_scope": "conversation",
                    "updated_at": datetime.now().isoformat(),
                },
            },
            {
                "id": "ctx-g2",
                "content": "另一个群在聊股票",
                "metadata": {
                    "memory_type": "context",
                    "source": "qq_robot_auto_promoted",
                    "robot_id": "robot-1",
                    "conversation_key": "group:g2",
                    "robot_conversation_key": "group:g2",
                    "memory_scope": "conversation",
                    "updated_at": datetime.now().isoformat(),
                },
            },
        ]

    def fake_search_memories(**_kwargs):
        return []

    monkeypatch.setattr(prompt_builder.vector_store, "get_all_memories", fake_get_all_memories)
    monkeypatch.setattr(prompt_builder.vector_store, "search_memories", fake_search_memories)

    memories = prompt_builder._collect_long_term_memories(
        "item-1",
        "现在什么情况",
        allowed_types=("fact", "preference", "task", "error", "context"),
        n_results=5,
        agent=agent,
    )

    assert "这个群正在开 Forge 服务器" in memories
    assert "另一个群在聊股票" not in memories


def test_robot_speaker_memory_does_not_cross_users_in_same_group(monkeypatch) -> None:
    agent = SimpleNamespace(
        _context=SimpleNamespace(
            robot_id="robot-1",
            robot_conversation_key="group:g1",
            robot_sender_key="onebot_v11:group:g1:u1",
        )
    )
    current_user = {
        "id": "pref-u1",
        "content": "用户偏好：Alice 以后叫她主人",
        "metadata": {
            "memory_type": "preference",
            "robot_id": "robot-1",
            "robot_conversation_key": "group:g1",
            "speaker_global_key": "onebot_v11:user:u1",
            "memory_scope": "speaker",
            "updated_at": datetime.now().isoformat(),
        },
    }
    other_user = {
        "id": "pref-u2",
        "content": "用户偏好：Bob 以后叫他大主人",
        "metadata": {
            "memory_type": "preference",
            "robot_id": "robot-1",
            "robot_conversation_key": "group:g1",
            "speaker_global_key": "onebot_v11:user:u2",
            "memory_scope": "speaker",
            "updated_at": datetime.now().isoformat(),
        },
    }

    monkeypatch.setattr(
        prompt_builder.vector_store,
        "get_all_memories",
        lambda *_args, **_kwargs: [current_user, other_user],
    )
    monkeypatch.setattr(
        prompt_builder.vector_store,
        "search_memories",
        lambda **_kwargs: [other_user, current_user],
    )

    memories = prompt_builder._collect_long_term_memories(
        "item-1",
        "我是谁",
        allowed_types=("fact", "preference", "error", "context"),
        n_results=5,
        agent=agent,
    )

    assert "Alice 以后叫她主人" in memories
    assert "Bob 以后叫他大主人" not in memories


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
