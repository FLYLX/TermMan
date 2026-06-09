from __future__ import annotations

import pytest

from app.core.config import settings
from app.services.agent.knowledge.service import KnowledgeBaseService


class FakeEmbeddingService:
    def encode(self, texts: list[str]) -> list[list[float]]:
        return [[1.0] for _ in texts]

    def encode_single(self, text: str) -> list[float]:
        return [1.0]


class FakeCollection:
    def __init__(self) -> None:
        self.add_calls: list[dict] = []
        self.delete_calls: list[list[str]] = []
        self.query_calls: list[dict] = []

    def delete(self, ids: list[str]) -> None:
        self.delete_calls.append(ids)

    def add(
        self,
        *,
        ids: list[str],
        embeddings: list[list[float]],
        documents: list[str],
        metadatas: list[dict],
    ) -> None:
        self.add_calls.append(
            {
                "ids": ids,
                "embeddings": embeddings,
                "documents": documents,
                "metadatas": metadatas,
            }
        )

    def query(self, **kwargs):
        self.query_calls.append(kwargs)
        return {
            "ids": [["chunk-1"]],
            "documents": [["Use docker compose up -d to start the stack."]],
            "metadatas": [[{"file_path": "guide.md", "file_name": "guide.md"}]],
            "distances": [[0.1]],
        }


@pytest.fixture()
def fake_knowledge_service(tmp_path, monkeypatch):
    service = KnowledgeBaseService()
    collection = FakeCollection()

    monkeypatch.setattr(settings, "KNOWLEDGE_BASE_DIR", str(tmp_path / "knowledge"))
    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))
    service._client = object()
    service._collection = collection
    service._embedding_service = FakeEmbeddingService()

    yield service, collection

    service._client = None
    service._collection = None
    service._embedding_service = None


def test_sync_library_does_not_reprocess_empty_indexed_files(fake_knowledge_service) -> None:
    service, collection = fake_knowledge_service
    files_dir = service._files_dir()
    (files_dir / "empty.md").write_text("   \n", encoding="utf-8")

    first_sync = service.sync_library()
    second_sync = service.sync_library()

    assert first_sync["added"] == ["empty.md"]
    assert second_sync["skipped"] == ["empty.md"]
    assert collection.add_calls == []


def test_search_skips_full_sync_when_enabled_files_are_current(
    fake_knowledge_service,
    monkeypatch,
) -> None:
    service, collection = fake_knowledge_service
    files_dir = service._files_dir()
    (files_dir / "guide.md").write_text(
        "Use docker compose up -d to start the stack.",
        encoding="utf-8",
    )
    service.sync_library()

    def fail_sync_library():
        raise AssertionError("search should not full-sync current knowledge files")

    monkeypatch.setattr(service, "sync_library", fail_sync_library)

    results = service.search("how to start stack", ["guide.md"], n_results=1)

    assert results[0]["content"] == "Use docker compose up -d to start the stack."
    assert collection.query_calls
