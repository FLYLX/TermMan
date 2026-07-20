from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from app.core.config import settings
from app.services.agent import task_watchdog
from app.services.agent.memory.vector_store import VectorStoreService, vector_store


class NearDuplicateEmbeddingService:
    """Fixed unit vectors: (主人喜欢猫, 主人喜欢猫咪) have cosine 0.9."""

    VECTORS = {
        "主人喜欢猫": [1.0, 0.0],
        "主人喜欢猫咪": [0.9, math.sqrt(0.19)],
        "服务器在东京机房": [0.0, 1.0],
    }

    def encode(self, texts: list[str]) -> list[list[float]]:
        return [self.VECTORS[text] for text in texts]

    def encode_single(self, text: str) -> list[float]:
        return self.VECTORS[text]


class FailingEmbeddingService:
    def encode(self, texts: list[str]) -> list[list[float]]:
        raise RuntimeError("embedding unavailable")

    def encode_single(self, text: str) -> list[float]:
        raise RuntimeError("embedding unavailable")


@pytest.fixture
def memory_store(monkeypatch, tmp_path):
    """VectorStoreService backed by the JSON fallback store in a tmp dir."""
    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIR", str(tmp_path))
    service = VectorStoreService()
    service._client = object()
    service._collection = None
    service._collection_embedding_model = None
    yield service
    for key in (
        "_client",
        "_collection",
        "_collection_embedding_model",
        "_embedding_service",
        "_lexical_index_path",
    ):
        service.__dict__.pop(key, None)
    VectorStoreService._lexical_index_path = None
    VectorStoreService._lexical_index_available = True


def _seed(service: VectorStoreService, item_id: str, contents: list[str]) -> None:
    for content in contents:
        service.add_memory(
            item_id=item_id,
            content=content,
            memory_type="fact",
            allow_duplicate=True,
        )


def test_dedup_merges_near_duplicates_with_embeddings(memory_store) -> None:
    memory_store._embedding_service = NearDuplicateEmbeddingService()
    _seed(memory_store, "item-1", ["主人喜欢猫", "主人喜欢猫咪", "服务器在东京机房"])

    removed = memory_store.deduplicate_memories("item-1", threshold=0.85)

    assert removed == 1
    remaining = [m["content"] for m in memory_store.get_all_memories("item-1")]
    assert remaining == ["主人喜欢猫", "服务器在东京机房"]


def test_dedup_default_threshold_keeps_looser_matches(memory_store) -> None:
    memory_store._embedding_service = NearDuplicateEmbeddingService()
    _seed(memory_store, "item-1", ["主人喜欢猫", "主人喜欢猫咪", "服务器在东京机房"])

    removed = memory_store.deduplicate_memories("item-1")

    assert removed == 0
    assert len(memory_store.get_all_memories("item-1")) == 3


def test_dedup_falls_back_to_lexical_when_embedding_unavailable(memory_store) -> None:
    memory_store._embedding_service = FailingEmbeddingService()
    _seed(memory_store, "item-1", ["用户密码是 hunter2", "用户密码是 hunter2", "今天天气很好"])

    removed = memory_store.deduplicate_memories("item-1", threshold=0.85)

    assert removed == 1
    remaining = [m["content"] for m in memory_store.get_all_memories("item-1")]
    assert remaining == ["用户密码是 hunter2", "今天天气很好"]


def test_dedup_lexical_fallback_keeps_distinct_memories(memory_store) -> None:
    memory_store._embedding_service = FailingEmbeddingService()
    _seed(memory_store, "item-1", ["用户喜欢喝冰美式", "服务器部署在东京机房"])

    removed = memory_store.deduplicate_memories("item-1", threshold=0.85)

    assert removed == 0
    assert len(memory_store.get_all_memories("item-1")) == 2


def test_watchdog_dedupes_memories_with_throttle(monkeypatch) -> None:
    calls: list[tuple[str, float]] = []

    monkeypatch.setattr(task_watchdog, "_list_all_item_ids", lambda: ["item-1"])
    monkeypatch.setattr(
        vector_store,
        "deduplicate_memories",
        lambda item_id, *, threshold: calls.append((item_id, threshold)) or 2,
    )
    task_watchdog._memory_dedup_last_run.clear()

    now = datetime.now(timezone.utc)
    stats = {"memories_deduplicated": 0}
    task_watchdog._dedupe_memory_clusters(now, stats)
    assert stats["memories_deduplicated"] == 2
    assert calls == [("item-1", task_watchdog.MEMORY_DEDUP_SIMILARITY_THRESHOLD)]

    # Second pass within the interval is throttled.
    task_watchdog._dedupe_memory_clusters(now, stats)
    assert stats["memories_deduplicated"] == 2
    assert len(calls) == 1

    # After the interval it runs again.
    later = datetime.fromtimestamp(
        now.timestamp() + task_watchdog.MEMORY_DEDUP_INTERVAL_SECONDS + 1,
        tz=timezone.utc,
    )
    task_watchdog._dedupe_memory_clusters(later, stats)
    assert stats["memories_deduplicated"] == 4

    task_watchdog._memory_dedup_last_run.clear()
