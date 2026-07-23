from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.agent.memory.vector_store import VectorStoreService
from app.services.agent.prompts.builder import _format_memories_with_conflict_hints


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


def _add(service, item_id, content, memory_key=None, updated_at=None):
    metadata = {}
    if memory_key:
        metadata["memory_key"] = memory_key
    if updated_at:
        metadata["updated_at"] = updated_at
    return service.add_memory(
        item_id=item_id,
        content=content,
        memory_type="fact",
        metadata=metadata,
        allow_duplicate=True,
        run_maintenance=False,
    )


class TestSupersedeByMemoryKey:
    def test_keeps_newest_per_key(self, memory_store):
        item = "item-1"
        _add(memory_store, item, "Java version is 17", memory_key="fact.java_version", updated_at="2026-07-01T00:00:00")
        _add(memory_store, item, "Java version is 21", memory_key="fact.java_version", updated_at="2026-07-20T00:00:00")
        _add(memory_store, item, "Server is in Tokyo", memory_key="fact.server_location", updated_at="2026-07-10T00:00:00")

        removed = memory_store.supersede_by_memory_key(item)
        assert removed == 1

        remaining = memory_store.get_all_memories(item)
        assert len(remaining) == 2
        contents = {m["content"] for m in remaining}
        assert "Java version is 21" in contents
        assert "Server is in Tokyo" in contents
        assert "Java version is 17" not in contents

    def test_no_key_no_supersession(self, memory_store):
        item = "item-2"
        _add(memory_store, item, "Memory A", updated_at="2026-07-01T00:00:00")
        _add(memory_store, item, "Memory B", updated_at="2026-07-20T00:00:00")

        removed = memory_store.supersede_by_memory_key(item)
        assert removed == 0
        assert len(memory_store.get_all_memories(item)) == 2

    def test_single_per_key_untouched(self, memory_store):
        item = "item-3"
        _add(memory_store, item, "Only one", memory_key="fact.solo", updated_at="2026-07-01T00:00:00")

        removed = memory_store.supersede_by_memory_key(item)
        assert removed == 0
        assert len(memory_store.get_all_memories(item)) == 1

    def test_three_same_key_keeps_newest(self, memory_store):
        item = "item-4"
        _add(memory_store, item, "v1", memory_key="fact.x", updated_at="2026-01-01T00:00:00")
        _add(memory_store, item, "v2", memory_key="fact.x", updated_at="2026-06-01T00:00:00")
        _add(memory_store, item, "v3", memory_key="fact.x", updated_at="2026-07-01T00:00:00")

        removed = memory_store.supersede_by_memory_key(item)
        assert removed == 2

        remaining = memory_store.get_all_memories(item)
        assert len(remaining) == 1
        assert remaining[0]["content"] == "v3"


class TestFormatMemoriesWithConflictHints:
    def test_no_conflict_no_annotation(self):
        memories = [
            {"content": "Java 21", "metadata": {"memory_key": "fact.java", "updated_at": "2026-07-20"}},
            {"content": "Server Tokyo", "metadata": {"memory_key": "fact.server", "updated_at": "2026-07-10"}},
        ]
        result = _format_memories_with_conflict_hints(memories)
        assert "[????]" not in result
        assert "- Java 21" in result
        assert "- Server Tokyo" in result

    def test_conflict_annotates_older(self):
        memories = [
            {"content": "Java 17", "metadata": {"memory_key": "fact.java", "updated_at": "2026-07-01"}},
            {"content": "Java 21", "metadata": {"memory_key": "fact.java", "updated_at": "2026-07-20"}},
        ]
        result = _format_memories_with_conflict_hints(memories)
        assert "[????] Java 17" in result
        assert "[????]" not in result.split("Java 21")[0].split("Java 17")[1] if "Java 21" in result else True
        lines = result.strip().split("\n")
        older_line = [l for l in lines if "Java 17" in l][0]
        newer_line = [l for l in lines if "Java 21" in l][0]
        assert "[????]" in older_line
        assert "[????]" not in newer_line

    def test_no_key_memories_never_annotated(self):
        memories = [
            {"content": "Random fact A", "metadata": {"updated_at": "2026-07-01"}},
            {"content": "Random fact B", "metadata": {"updated_at": "2026-07-20"}},
        ]
        result = _format_memories_with_conflict_hints(memories)
        assert "[????]" not in result
