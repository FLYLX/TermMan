from pathlib import Path

from fastapi.testclient import TestClient
from sqlmodel import Session

from app.core.config import settings
from app.services.agent.knowledge import knowledge_base_service
from tests.utils.item_handler import create_random_item_handler


def test_shared_knowledge_routes_and_item_handler_binding(
    client: TestClient,
    superuser_token_headers: dict[str, str],
    db: Session,
    monkeypatch,
    tmp_path: Path,
) -> None:
    item_handler = create_random_item_handler(db)
    knowledge_base_service._client = None
    knowledge_base_service._collection = None
    knowledge_base_service._embedding_service = None
    monkeypatch.setattr(settings, "KNOWLEDGE_BASE_DIR", str(tmp_path / "knowledge"))
    monkeypatch.setattr(settings, "CHROMA_PERSIST_DIR", str(tmp_path / "chroma"))

    upload_response = client.post(
        f"{settings.API_V1_STR}/knowledge/files/upload",
        headers=superuser_token_headers,
        files=[
            ("files", ("guide.md", b"# Guide\nhello", "text/markdown")),
            ("files", ("notes.txt", b"plain text", "text/plain")),
        ],
    )
    assert upload_response.status_code == 200
    assert upload_response.json()["count"] == 2

    library_response = client.get(
        f"{settings.API_V1_STR}/knowledge/files",
        headers=superuser_token_headers,
    )
    assert library_response.status_code == 200
    listed_paths = {entry["path"] for entry in library_response.json()["data"]}
    assert listed_paths == {"guide.md", "notes.txt"}

    enable_response = client.put(
        f"{settings.API_V1_STR}/item-handlers/{item_handler.id}",
        headers=superuser_token_headers,
        json={"enabled_knowledge_files": ["guide.md"]},
    )
    assert enable_response.status_code == 200
    assert enable_response.json()["enabled_knowledge_files"] == ["guide.md"]

    binding_response = client.get(
        f"{settings.API_V1_STR}/item-handlers/{item_handler.id}/knowledge/files",
        headers=superuser_token_headers,
    )
    assert binding_response.status_code == 200
    binding_map = {
        entry["path"]: entry["enabled"]
        for entry in binding_response.json()["data"]
    }
    assert binding_map == {"guide.md": True, "notes.txt": False}

    download_response = client.get(
        f"{settings.API_V1_STR}/knowledge/files/download/guide.md",
        headers=superuser_token_headers,
    )
    assert download_response.status_code == 200
    assert download_response.content == b"# Guide\nhello"
    assert "guide.md" in download_response.headers["content-disposition"]

    delete_response = client.delete(
        f"{settings.API_V1_STR}/knowledge/files/guide.md",
        headers=superuser_token_headers,
    )
    assert delete_response.status_code == 200

    library_response = client.get(
        f"{settings.API_V1_STR}/knowledge/files",
        headers=superuser_token_headers,
    )
    assert library_response.status_code == 200
    listed_paths = {entry["path"] for entry in library_response.json()["data"]}
    assert listed_paths == {"notes.txt"}

    item_handler_response = client.get(
        f"{settings.API_V1_STR}/item-handlers/{item_handler.id}",
        headers=superuser_token_headers,
    )
    assert item_handler_response.status_code == 200
    assert item_handler_response.json()["enabled_knowledge_files"] == []
