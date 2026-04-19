from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path, PurePosixPath
from typing import Any

import chromadb
from chromadb import Collection

from app.core.config import settings
from app.services.agent.memory.vector_store import EmbeddingService

logger = logging.getLogger(__name__)

SUPPORTED_KNOWLEDGE_EXTENSIONS = {".md", ".markdown", ".txt"}
DEFAULT_KNOWLEDGE_RESULTS = 4
DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 180


class KnowledgeBaseService:
    _instance: "KnowledgeBaseService | None" = None
    _client: Any = None
    _collection: Collection | None = None
    _embedding_service: EmbeddingService | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        pass

    def _storage_root(self) -> Path:
        return Path(settings.KNOWLEDGE_BASE_DIR)

    def _files_dir(self) -> Path:
        path = self._storage_root() / "files"
        path.mkdir(parents=True, exist_ok=True)
        return path

    def _index_path(self) -> Path:
        root = self._storage_root()
        root.mkdir(parents=True, exist_ok=True)
        return root / "index.json"

    def _ensure_initialized(self):
        if self._client is not None:
            return

        self._storage_root().mkdir(parents=True, exist_ok=True)
        Path(settings.CHROMA_PERSIST_DIR).mkdir(parents=True, exist_ok=True)

        self._client = chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)
        self._collection = self._client.get_or_create_collection(
            name="shared_knowledge",
            metadata={"description": "Shared knowledge documents indexed for item handlers"},
        )
        self._embedding_service = EmbeddingService()

    def normalize_relative_path(self, raw_path: str) -> str:
        candidate = (raw_path or "").replace("\\", "/").strip().lstrip("/")
        if not candidate:
            raise ValueError("Path is required")

        normalized = PurePosixPath(candidate)
        if normalized.is_absolute():
            raise ValueError("Absolute paths are not allowed")
        if any(part in {"", ".", ".."} for part in normalized.parts):
            raise ValueError("Invalid path")

        normalized_path = "/".join(normalized.parts)
        if not self.is_supported_file(normalized_path):
            raise ValueError("Only .md, .markdown, and .txt knowledge files are supported")
        return normalized_path

    def normalize_enabled_files(self, file_paths: list[str] | None) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for raw_path in file_paths or []:
            try:
                file_path = self.normalize_relative_path(raw_path)
            except ValueError:
                continue
            if file_path in seen:
                continue
            seen.add(file_path)
            normalized.append(file_path)
        return normalized

    @staticmethod
    def is_supported_file(path: str) -> bool:
        return Path(path).suffix.lower() in SUPPORTED_KNOWLEDGE_EXTENSIONS

    def _read_index(self) -> dict[str, Any]:
        index_path = self._index_path()
        if not index_path.exists():
            return {"version": 1, "files": {}}

        try:
            payload = json.loads(index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            logger.warning("[Knowledge] Invalid index, rebuilding")
            return {"version": 1, "files": {}}

        if not isinstance(payload, dict):
            return {"version": 1, "files": {}}
        files = payload.get("files")
        if not isinstance(files, dict):
            payload["files"] = {}
        payload.setdefault("version", 1)
        return payload

    def _write_index(self, payload: dict[str, Any]) -> None:
        self._index_path().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    def get_existing_relative_paths(self) -> list[str]:
        files_dir = self._files_dir()
        relative_paths: list[str] = []
        for path in files_dir.rglob("*"):
            if not path.is_file():
                continue
            relative_path = path.relative_to(files_dir).as_posix()
            if self.is_supported_file(relative_path):
                relative_paths.append(relative_path)
        return sorted(relative_paths)

    def save_file_bytes(self, filename: str, content: bytes) -> dict[str, Any]:
        self._ensure_initialized()
        relative_path = self.normalize_relative_path(Path(filename or "").name)
        destination = self._files_dir() / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(content)
        stat = destination.stat()
        return {
            "path": relative_path,
            "name": destination.name,
            "size": stat.st_size,
            "modified_at": int(stat.st_mtime),
        }

    def get_file_absolute_path(self, file_path: str) -> Path:
        self._ensure_initialized()
        relative_path = self.normalize_relative_path(file_path)
        absolute_path = self._files_dir() / relative_path
        if not absolute_path.exists() or not absolute_path.is_file():
            raise FileNotFoundError(relative_path)
        return absolute_path

    def list_files(self, enabled_files: list[str] | None = None) -> list[dict[str, Any]]:
        self._ensure_initialized()
        self.sync_library()

        enabled_set = set(self.normalize_enabled_files(enabled_files))
        index = self._read_index()
        index_files = index.get("files", {})
        files_dir = self._files_dir()

        file_entries: dict[str, dict[str, Any]] = {}
        for relative_path in self.get_existing_relative_paths():
            absolute_path = files_dir / relative_path
            stat = absolute_path.stat()
            indexed_entry = index_files.get(relative_path, {})
            file_entries[relative_path] = {
                "path": relative_path,
                "name": absolute_path.name,
                "size": stat.st_size,
                "modified_at": int(stat.st_mtime),
                "enabled": relative_path in enabled_set,
                "indexed": bool(indexed_entry.get("chunk_ids")),
                "missing": False,
                "chunk_count": len(indexed_entry.get("chunk_ids", [])),
            }

        for relative_path in enabled_set:
            if relative_path in file_entries:
                continue
            indexed_entry = index_files.get(relative_path, {})
            file_entries[relative_path] = {
                "path": relative_path,
                "name": Path(relative_path).name,
                "size": None,
                "modified_at": None,
                "enabled": True,
                "indexed": bool(indexed_entry.get("chunk_ids")),
                "missing": True,
                "chunk_count": len(indexed_entry.get("chunk_ids", [])),
            }

        return sorted(
            file_entries.values(),
            key=lambda entry: (
                0 if entry["enabled"] else 1,
                0 if not entry["missing"] else 1,
                entry["name"].lower(),
            ),
        )

    def _delete_chunk_ids(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        self._collection.delete(ids=chunk_ids)

    def _remove_indexed_entry(self, index_payload: dict[str, Any], file_path: str) -> bool:
        entry = index_payload.get("files", {}).pop(file_path, None)
        if not entry:
            return False
        chunk_ids = entry.get("chunk_ids", [])
        if isinstance(chunk_ids, list):
            self._delete_chunk_ids(chunk_ids)
        return True

    @staticmethod
    def _decode_content(raw_bytes: bytes) -> str:
        for encoding in ("utf-8", "utf-8-sig", "gb18030", "latin-1"):
            try:
                return raw_bytes.decode(encoding)
            except UnicodeDecodeError:
                continue
        return raw_bytes.decode("utf-8", errors="ignore")

    @staticmethod
    def _chunk_text(text: str) -> list[str]:
        content = text.strip()
        if not content:
            return []
        if len(content) <= DEFAULT_CHUNK_SIZE:
            return [content]

        chunks: list[str] = []
        start = 0
        content_length = len(content)
        while start < content_length:
            target_end = min(start + DEFAULT_CHUNK_SIZE, content_length)
            end = target_end
            if target_end < content_length:
                scan_start = min(target_end, start + DEFAULT_CHUNK_SIZE // 2)
                for separator in ("\n\n", "\n", " "):
                    separator_index = content.rfind(separator, scan_start, target_end)
                    if separator_index > start:
                        end = separator_index + len(separator)
                        break

            chunk = content[start:end].strip()
            if chunk:
                chunks.append(chunk)

            if end >= content_length:
                break

            start = max(0, end - DEFAULT_CHUNK_OVERLAP)
            if start >= content_length:
                break
        return chunks

    @staticmethod
    def _build_chunk_id(file_path: str, content_hash: str, index: int) -> str:
        digest = hashlib.sha1(file_path.encode("utf-8")).hexdigest()[:16]
        return f"knowledge:{digest}:{content_hash[:16]}:{index}"

    def sync_library(self) -> dict[str, Any]:
        self._ensure_initialized()
        existing_paths = set(self.get_existing_relative_paths())
        files_dir = self._files_dir()
        index_payload = self._read_index()

        added: list[str] = []
        updated: list[str] = []
        removed: list[str] = []
        skipped: list[str] = []

        for indexed_path in list(index_payload.get("files", {}).keys()):
            if indexed_path not in existing_paths:
                if self._remove_indexed_entry(index_payload, indexed_path):
                    removed.append(indexed_path)

        for file_path in sorted(existing_paths):
            absolute_path = files_dir / file_path
            stat = absolute_path.stat()
            current_entry = index_payload.get("files", {}).get(file_path)

            if (
                current_entry
                and current_entry.get("mtime_ns") == stat.st_mtime_ns
                and current_entry.get("size") == stat.st_size
                and current_entry.get("chunk_ids")
            ):
                skipped.append(file_path)
                continue

            raw_bytes = absolute_path.read_bytes()
            content_hash = hashlib.sha256(raw_bytes).hexdigest()
            text = self._decode_content(raw_bytes)

            if (
                current_entry
                and current_entry.get("content_hash") == content_hash
                and current_entry.get("chunk_ids")
            ):
                current_entry["mtime_ns"] = stat.st_mtime_ns
                current_entry["size"] = stat.st_size
                current_entry["updated_at"] = int(stat.st_mtime)
                index_payload["files"][file_path] = current_entry
                skipped.append(file_path)
                continue

            if current_entry:
                self._delete_chunk_ids(current_entry.get("chunk_ids", []))

            chunks = self._chunk_text(text)
            chunk_ids: list[str] = []
            if chunks:
                chunk_ids = [
                    self._build_chunk_id(file_path, content_hash, index)
                    for index in range(len(chunks))
                ]
                try:
                    self._collection.delete(ids=chunk_ids)
                except Exception:
                    logger.debug("[Knowledge] Ignored cleanup failure before add", exc_info=True)

                embeddings = self._embedding_service.encode(chunks)
                metadatas = [
                    {
                        "file_path": file_path,
                        "file_name": Path(file_path).name,
                        "chunk_index": index,
                        "content_hash": content_hash,
                        "source_type": "knowledge_file",
                    }
                    for index in range(len(chunks))
                ]
                self._collection.add(
                    ids=chunk_ids,
                    embeddings=embeddings,
                    documents=chunks,
                    metadatas=metadatas,
                )

            index_payload["files"][file_path] = {
                "file_name": Path(file_path).name,
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "updated_at": int(stat.st_mtime),
                "content_hash": content_hash,
                "chunk_ids": chunk_ids,
            }

            if current_entry:
                updated.append(file_path)
            else:
                added.append(file_path)

        self._write_index(index_payload)
        return {
            "added": added,
            "updated": updated,
            "removed": removed,
            "skipped": skipped,
        }

    def search(
        self,
        query: str,
        enabled_files: list[str] | None,
        n_results: int = DEFAULT_KNOWLEDGE_RESULTS,
    ) -> list[dict[str, Any]]:
        normalized_enabled = self.normalize_enabled_files(enabled_files)
        if not normalized_enabled or not (query or "").strip():
            return []

        self._ensure_initialized()
        self.sync_library()
        query_embedding = self._embedding_service.encode_single(query.strip())

        entries_by_id: dict[str, dict[str, Any]] = {}
        for file_path in normalized_enabled:
            try:
                results = self._collection.query(
                    query_embeddings=[query_embedding],
                    n_results=n_results,
                    where={"file_path": file_path},
                )
            except Exception as exc:
                logger.warning(
                    "[Knowledge] Failed to query knowledge for file=%s: %s",
                    file_path,
                    exc,
                )
                continue

            documents = results.get("documents") or []
            if not documents or not documents[0]:
                continue

            for index, content in enumerate(documents[0]):
                entry = {
                    "id": results["ids"][0][index],
                    "content": content,
                    "metadata": results["metadatas"][0][index] if results.get("metadatas") else {},
                    "distance": results["distances"][0][index] if results.get("distances") else None,
                }
                existing = entries_by_id.get(entry["id"])
                if existing is None or (entry["distance"] or 0) < (existing["distance"] or 0):
                    entries_by_id[entry["id"]] = entry

        entries = list(entries_by_id.values())
        entries.sort(key=lambda entry: entry.get("distance") or 0)
        return entries[:n_results]

    def delete_file(self, file_path: str) -> bool:
        self._ensure_initialized()
        relative_path = self.normalize_relative_path(file_path)
        index_payload = self._read_index()
        self._remove_indexed_entry(index_payload, relative_path)
        self._write_index(index_payload)

        absolute_path = self._files_dir() / relative_path
        if not absolute_path.exists():
            return False

        absolute_path.unlink()
        parent = absolute_path.parent
        files_dir = self._files_dir()
        while parent != files_dir and parent.exists():
            try:
                parent.rmdir()
            except OSError:
                break
            parent = parent.parent
        return True


knowledge_base_service = KnowledgeBaseService()
