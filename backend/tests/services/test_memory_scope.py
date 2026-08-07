"""Handler-native memory scoping tests.

Long-term memories are keyed by ItemHandler id end to end: the vector store
persists `handler_id` metadata, and boundary resolution maps a raw item id
to its driving handler via ItemHandlerItem (falling back to the raw id for
unlinked items). Each memory also carries `source_item_id` so recall can
prioritize and label the terminal the fact came from.
"""
from __future__ import annotations

from sqlmodel import Session

from app.models import ItemHandlerItem
from app.services.agent.memory.scope import (
    handler_item_directory,
    item_titles,
    resolve_handler_id,
)
from app.services.agent.memory.vector_store import VectorStoreService
from tests.utils.item import create_random_item
from tests.utils.item_handler import create_random_item_handler


class _FailingEmbeddingService:
    def encode_single(self, text: str) -> list[float]:
        raise RuntimeError("embedding unavailable")


def _fallback_store(monkeypatch, tmp_path) -> VectorStoreService:
    from app.core.config import settings

    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIR", str(tmp_path))
    service = VectorStoreService()
    service._client = object()
    service._collection = None
    service._embedding_service = _FailingEmbeddingService()
    return service


def test_resolve_handler_id_uses_item_handler_association(db: Session) -> None:
    item = create_random_item(db)
    handler = create_random_item_handler(db)
    db.add(ItemHandlerItem(item_id=item.id, item_handler_id=handler.id))
    db.commit()

    assert resolve_handler_id(str(item.id)) == str(handler.id)


def test_resolve_handler_id_falls_back_to_raw_item_id(db: Session) -> None:
    item = create_random_item(db)

    assert resolve_handler_id(str(item.id)) == str(item.id)
    assert resolve_handler_id("not-a-uuid") == "not-a-uuid"
    assert resolve_handler_id("") == ""


def test_memories_are_stored_and_filtered_by_handler_id(
    monkeypatch, tmp_path
) -> None:
    service = _fallback_store(monkeypatch, tmp_path)
    try:
        memory_id = service.add_memory(
            handler_id="handler-a",
            content="服务器端口是 43906",
            memory_type="fact",
        )
        service.add_memory(
            handler_id="handler-b",
            content="其他 handler 的事实",
            memory_type="fact",
        )

        assert memory_id is not None
        stored = service.get_memory(memory_id)
        assert stored is not None
        assert stored["metadata"]["handler_id"] == "handler-a"
        assert "item_id" not in stored["metadata"]

        handler_a = service.get_all_memories("handler-a")
        assert [memory["id"] for memory in handler_a] == [memory_id]

        results = service.search_memories(
            handler_id="handler-a", query="43906", n_results=5
        )
        assert [memory["id"] for memory in results] == [memory_id]

        service.delete_handler_memories("handler-a")
        assert service.get_all_memories("handler-a") == []
        assert len(service.get_all_memories("handler-b")) == 1
    finally:
        service._client = None
        service._collection = None
        service._embedding_service = None
        service._lexical_index_path = None

def test_handler_item_directory_lists_all_handler_items(db: Session) -> None:
    item_a = create_random_item(db)
    item_b = create_random_item(db)
    handler = create_random_item_handler(db)
    db.add(ItemHandlerItem(item_id=item_a.id, item_handler_id=handler.id))
    db.add(ItemHandlerItem(item_id=item_b.id, item_handler_id=handler.id))
    db.commit()

    handler_id, items = handler_item_directory(str(item_a.id))

    assert handler_id == str(handler.id)
    assert items[0] == {"item_id": str(item_a.id), "title": item_a.title}
    assert {entry["item_id"] for entry in items} == {str(item_a.id), str(item_b.id)}


def test_handler_item_directory_falls_back_without_association(db: Session) -> None:
    item = create_random_item(db)

    handler_id, items = handler_item_directory(str(item.id))

    assert handler_id == str(item.id)
    assert items == [{"item_id": str(item.id), "title": item.title}]


def test_item_titles_batch_lookup(db: Session) -> None:
    item = create_random_item(db)

    titles = item_titles([str(item.id), "not-a-uuid"])

    assert titles == {str(item.id): item.title}


def test_prompt_labels_cross_terminal_memory_sources(db: Session, monkeypatch) -> None:
    from app.services.agent.prompts import builder as prompt_builder

    item_a = create_random_item(db)
    item_b = create_random_item(db)
    handler = create_random_item_handler(db)
    db.add(ItemHandlerItem(item_id=item_a.id, item_handler_id=handler.id))
    db.add(ItemHandlerItem(item_id=item_b.id, item_handler_id=handler.id))
    db.commit()

    foreign_memory = {
        "id": "mem-b",
        "content": "B 终端的端口是 25565",
        "metadata": {"memory_type": "fact", "source_item_id": str(item_b.id)},
        "distance": 0.1,
    }
    own_memory = {
        "id": "mem-a",
        "content": "A 终端的端口是 43906",
        "metadata": {"memory_type": "fact", "source_item_id": str(item_a.id)},
        "distance": 0.2,
    }
    monkeypatch.setattr(
        prompt_builder.vector_store,
        "get_all_memories",
        lambda *_args, **_kwargs: [foreign_memory, own_memory],
    )
    monkeypatch.setattr(
        prompt_builder.vector_store,
        "search_memories",
        lambda **_kwargs: [foreign_memory, own_memory],
    )

    context, label = prompt_builder._terminal_identity(str(item_a.id))
    assert item_a.title in context
    assert item_b.title in context
    assert label == item_a.title

    memories = prompt_builder._collect_long_term_memories(
        str(item_a.id),
        "端口",
        allowed_types=("fact",),
        n_results=5,
        agent=None,
    )
    assert f"[from {item_b.title}]" in memories
    assert f"[from {item_a.title}]" not in memories
    # Current terminal's memory ranks first.
    assert memories.index("43906") < memories.index("25565")
