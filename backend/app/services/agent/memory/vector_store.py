import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

import chromadb
from chromadb import Collection

from app.core.config import settings

logger = logging.getLogger(__name__)

MemoryType = Literal["fact", "preference", "task", "error", "context"]

MEMORY_TYPES = {
    "fact": "事实信息：用户名、路径、配置值等",
    "preference": "用户偏好：代码风格、工具选择等",
    "task": "任务相关：待办事项、计划等",
    "error": "错误记录：已知问题和解决方案",
    "context": "上下文：项目结构、依赖关系等",
}

DEFAULT_MEMORY_TTL_DAYS = 30
DEDUP_THRESHOLD = 0.95
SUMMARIZE_THRESHOLD = 10
DEFAULT_RECALL_CANDIDATE_MULTIPLIER = 4


class EmbeddingService:
    _instance: "EmbeddingService | None" = None
    _model: Any | None = None
    _load_error: str | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        pass

    def _ensure_model(self):
        if self._load_error is not None:
            raise RuntimeError(self._load_error)

        if self._model is None:
            logger.info("[Embedding] Loading all-MiniLM-L6-v2 model...")
            from sentence_transformers import SentenceTransformer

            try:
                self._model = SentenceTransformer("all-MiniLM-L6-v2")
                logger.info("[Embedding] Model loaded successfully")
            except Exception as e:
                self._load_error = str(e)
                logger.warning(
                    "[Embedding] Model unavailable; long-term memory search/write will be skipped: %s",
                    e,
                )
                raise

    def encode(self, texts: str | list[str]) -> list[list[float]]:
        self._ensure_model()
        if isinstance(texts, str):
            texts = [texts]
        embeddings = self._model.encode(texts, convert_to_numpy=True)
        return embeddings.tolist()

    def encode_single(self, text: str) -> list[float]:
        return self.encode([text])[0]


class VectorStoreService:
    _instance: "VectorStoreService | None" = None
    _client: Any = None
    _collection: Collection | None = None
    _embedding_service: EmbeddingService | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        pass

    def _ensure_initialized(self):
        if self._client is not None:
            return

        persist_dir = settings.CHROMA_PERSIST_DIR
        os.makedirs(persist_dir, exist_ok=True)

        logger.info(f"[VectorStore] Initializing ChromaDB with persistence at {persist_dir}")
        self._client = chromadb.PersistentClient(path=persist_dir)
        self._collection = self._client.get_or_create_collection(
            name="item_memories",
            metadata={"description": "Long-term memory for items"},
        )
        self._embedding_service = EmbeddingService()
        logger.info("[VectorStore] ChromaDB initialized with persistence")

    def _try_encode_single(self, text: str) -> list[float] | None:
        try:
            return self._embedding_service.encode_single(text)
        except Exception as e:
            logger.warning("[VectorStore] Skipping memory embedding: %s", e)
            return None

    def _try_encode(self, texts: list[str]) -> list[list[float]] | None:
        try:
            return self._embedding_service.encode(texts)
        except Exception as e:
            logger.warning("[VectorStore] Skipping memory embeddings: %s", e)
            return None

    @staticmethod
    def _build_where_filter(
        item_id: str | None = None,
        memory_type: MemoryType | None = None,
    ) -> dict[str, Any] | None:
        filters: list[dict[str, Any]] = []
        if item_id:
            filters.append({"item_id": item_id})
        if memory_type:
            filters.append({"memory_type": memory_type})

        if not filters:
            return None
        if len(filters) == 1:
            return filters[0]
        return {"$and": filters}

    @staticmethod
    def _parse_datetime(value: Any) -> datetime | None:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    @classmethod
    def _is_expired_memory(cls, metadata: dict[str, Any]) -> bool:
        expires_at = cls._parse_datetime(metadata.get("expires_at"))
        if expires_at is None:
            return False
        now = datetime.now(expires_at.tzinfo) if expires_at.tzinfo else datetime.now()
        return expires_at < now

    @staticmethod
    def _resolved_memory_status(memory_type: str, content: str, metadata: dict[str, Any]) -> str:
        status = str(metadata.get("status") or "").lower()
        if status:
            return status
        normalized = (content or "").strip()
        if memory_type == "task":
            if normalized.endswith("\uff08\u5df2\u5b8c\u6210\uff09"):
                return "completed"
            return "active"
        if memory_type == "error":
            if normalized.endswith("\uff08\u5df2\u89e3\u51b3\uff09"):
                return "resolved"
            return "active"
        return ""

    @classmethod
    def _is_inactive_status_memory(cls, content: str, metadata: dict[str, Any]) -> bool:
        memory_type = str(metadata.get("memory_type") or "")
        status = cls._resolved_memory_status(memory_type, content, metadata)
        return (
            (memory_type == "task" and status == "completed")
            or (memory_type == "error" and status == "resolved")
        )

    @staticmethod
    def _similarity_from_distance(distance: Any) -> float | None:
        if distance is None:
            return None
        try:
            return 1.0 - float(distance)
        except (TypeError, ValueError):
            return None

    def add_memory(
        self,
        item_id: str,
        content: str,
        memory_type: MemoryType = "fact",
        metadata: dict[str, Any] | None = None,
        memory_id: str | None = None,
        ttl_days: int | None = None,
    ) -> str | None:
        self._ensure_initialized()
        if memory_id is None:
            memory_id = str(uuid.uuid4())

        existing = self._check_duplicate(item_id, content)
        if existing:
            logger.info(f"[VectorStore] Skipping duplicate memory for item {item_id}")
            return None

        embedding = self._try_encode_single(content)
        if embedding is None:
            return None

        ttl = ttl_days or DEFAULT_MEMORY_TTL_DAYS
        expires_at = (datetime.now() + timedelta(days=ttl)).isoformat()

        meta = metadata or {}
        meta["item_id"] = item_id
        meta["memory_type"] = memory_type
        meta["created_at"] = datetime.now().isoformat()
        meta["expires_at"] = expires_at

        self._collection.add(
            ids=[memory_id],
            embeddings=[embedding],
            documents=[content],
            metadatas=[meta],
        )

        logger.info(f"[VectorStore] Added {memory_type} memory {memory_id} for item {item_id}")
        return memory_id

    def _check_duplicate(self, item_id: str, content: str) -> bool:
        self._ensure_initialized()
        query_embedding = self._try_encode_single(content)
        if query_embedding is None:
            return False

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=1,
            where={"item_id": item_id},
        )

        if results["distances"] and results["distances"][0]:
            distance = results["distances"][0][0]
            similarity = 1 - distance
            return similarity >= DEDUP_THRESHOLD

        return False

    def search_memories(
        self,
        item_id: str,
        query: str,
        n_results: int = 5,
        memory_type: MemoryType | None = None,
        *,
        include_expired: bool = False,
        active_only: bool = True,
        min_similarity: float | None = None,
        candidate_multiplier: int = DEFAULT_RECALL_CANDIDATE_MULTIPLIER,
    ) -> list[dict[str, Any]]:
        self._ensure_initialized()
        query_embedding = self._try_encode_single(query)
        if query_embedding is None:
            return []
        where_filter = self._build_where_filter(item_id=item_id, memory_type=memory_type)
        query_results = max(n_results, n_results * max(candidate_multiplier, 1))

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=query_results,
            where=where_filter,
        )

        memories = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                distance = results["distances"][0][i] if results["distances"] else None
                if not include_expired and self._is_expired_memory(metadata):
                    continue
                if active_only and self._is_inactive_status_memory(doc, metadata):
                    continue
                similarity = self._similarity_from_distance(distance)
                if (
                    min_similarity is not None
                    and similarity is not None
                    and similarity < min_similarity
                ):
                    continue
                memory = {
                    "id": results["ids"][0][i],
                    "content": doc,
                    "metadata": metadata,
                    "distance": distance,
                }
                memories.append(memory)
                if len(memories) >= n_results:
                    break

        return memories

    def get_all_memories(
        self,
        item_id: str,
        memory_type: MemoryType | None = None,
    ) -> list[dict[str, Any]]:
        self._ensure_initialized()
        where_filter = self._build_where_filter(item_id=item_id, memory_type=memory_type)

        results = self._collection.get(where=where_filter)

        memories = []
        if results["ids"]:
            for i, memory_id in enumerate(results["ids"]):
                memories.append({
                    "id": memory_id,
                    "content": results["documents"][i] if results["documents"] else "",
                    "metadata": results["metadatas"][i] if results["metadatas"] else {},
                })

        return memories

    def get_memory(self, memory_id: str) -> dict[str, Any] | None:
        self._ensure_initialized()
        results = self._collection.get(ids=[memory_id])
        if not results["ids"]:
            return None
        return {
            "id": results["ids"][0],
            "content": results["documents"][0] if results["documents"] else "",
            "metadata": results["metadatas"][0] if results["metadatas"] else {},
        }

    def get_memory_stats(self, item_id: str) -> dict[str, Any]:
        all_memories = self.get_all_memories(item_id)

        stats = {
            "total": len(all_memories),
            "by_type": {},
            "expired_count": 0,
        }

        now = datetime.now()
        for memory in all_memories:
            meta = memory.get("metadata", {})
            m_type = meta.get("memory_type", "fact")
            stats["by_type"][m_type] = stats["by_type"].get(m_type, 0) + 1

            expires_at = meta.get("expires_at")
            if expires_at:
                try:
                    exp_time = datetime.fromisoformat(expires_at)
                    if exp_time < now:
                        stats["expired_count"] += 1
                except ValueError:
                    pass

        return stats

    def delete_memory(self, memory_id: str) -> bool:
        self._ensure_initialized()
        try:
            self._collection.delete(ids=[memory_id])
            logger.info(f"[VectorStore] Deleted memory {memory_id}")
            return True
        except Exception as e:
            logger.error(f"[VectorStore] Failed to delete memory {memory_id}: {e}")
            return False

    def delete_item_memories(self, item_id: str):
        self._ensure_initialized()
        self._collection.delete(where={"item_id": item_id})
        logger.info(f"[VectorStore] Deleted all memories for item {item_id}")

    def expire_old_memories(self, item_id: str) -> int:
        all_memories = self.get_all_memories(item_id)
        now = datetime.now()
        expired_ids = []

        for memory in all_memories:
            meta = memory.get("metadata", {})
            expires_at = meta.get("expires_at")
            if expires_at:
                try:
                    exp_time = datetime.fromisoformat(expires_at)
                    if exp_time < now:
                        expired_ids.append(memory["id"])
                except ValueError:
                    pass

        if expired_ids:
            self._collection.delete(ids=expired_ids)
            logger.info(f"[VectorStore] Expired {len(expired_ids)} memories for item {item_id}")

        return len(expired_ids)

    def deduplicate_memories(self, item_id: str) -> int:
        all_memories = self.get_all_memories(item_id)
        if len(all_memories) < 2:
            return 0

        contents = [m["content"] for m in all_memories]
        embeddings = self._try_encode(contents)
        if embeddings is None:
            return 0

        ids_to_delete = set()

        for i in range(len(embeddings)):
            if all_memories[i]["id"] in ids_to_delete:
                continue
            for j in range(i + 1, len(embeddings)):
                if all_memories[j]["id"] in ids_to_delete:
                    continue

                similarity = self._cosine_similarity(embeddings[i], embeddings[j])
                if similarity >= DEDUP_THRESHOLD:
                    ids_to_delete.add(all_memories[j]["id"])

        if ids_to_delete:
            self._collection.delete(ids=list(ids_to_delete))
            logger.info(f"[VectorStore] Deduplicated {len(ids_to_delete)} memories for item {item_id}")

        return len(ids_to_delete)

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        import numpy as np
        a_arr = np.array(a)
        b_arr = np.array(b)
        return np.dot(a_arr, b_arr) / (np.linalg.norm(a_arr) * np.linalg.norm(b_arr))

    def get_memories_by_type(self, item_id: str, memory_type: MemoryType) -> list[dict[str, Any]]:
        return self.get_all_memories(item_id, memory_type=memory_type)

    def update_memory(self, memory_id: str, content: str | None = None, metadata: dict[str, Any] | None = None) -> bool:
        self._ensure_initialized()
        try:
            existing = self._collection.get(ids=[memory_id])
            if not existing["ids"]:
                return False

            current_meta = existing["metadatas"][0] if existing["metadatas"] else {}
            current_doc = existing["documents"][0] if existing["documents"] else ""

            new_content = content or current_doc
            new_meta = {**current_meta, **(metadata or {})}

            embedding = self._try_encode_single(new_content)
            if embedding is None:
                return False

            self._collection.delete(ids=[memory_id])
            self._collection.add(
                ids=[memory_id],
                embeddings=[embedding],
                documents=[new_content],
                metadatas=[new_meta],
            )

            logger.info(f"[VectorStore] Updated memory {memory_id}")
            return True
        except Exception as e:
            logger.error(f"[VectorStore] Failed to update memory {memory_id}: {e}")
            return False

    def get_item_memory_count(self, item_id: str) -> int:
        self._ensure_initialized()
        results = self._collection.get(where={"item_id": item_id})
        return len(results["ids"]) if results["ids"] else 0

    def summarize_memories(
        self,
        item_id: str,
        model: str = "deepseek/deepseek-chat",
        api_key: str | None = None,
        api_base: str | None = None,
        threshold: int = 10,
    ) -> dict[str, Any]:
        all_memories = self.get_all_memories(item_id)

        if len(all_memories) < threshold:
            return {"summarized": 0, "message": f"记忆数量 ({len(all_memories)}) 未达到阈值 ({threshold})"}

        from litellm import completion

        memories_by_type: dict[str, list[dict]] = {}
        for memory in all_memories:
            m_type = memory.get("metadata", {}).get("memory_type", "fact")
            if m_type not in memories_by_type:
                memories_by_type[m_type] = []
            memories_by_type[m_type].append(memory)

        total_summarized = 0
        summaries_created = 0

        for m_type, memories in memories_by_type.items():
            if len(memories) < 3:
                continue

            contents = [m["content"] for m in memories]
            combined = "\n".join(f"- {c}" for c in contents)

            prompt = f"""请将以下 {len(memories)} 条{MEMORY_TYPES.get(m_type, m_type)}记忆压缩成 1-3 条精简的摘要。
保留关键信息，去除重复和冗余内容。

原始记忆:
{combined}

请直接输出压缩后的记忆，每条一行，不要编号或其他格式。"""

            try:
                kwargs = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 500,
                }
                if api_key:
                    kwargs["api_key"] = api_key
                if api_base:
                    kwargs["api_base"] = api_base

                response = completion(**kwargs)
                summary_text = response.choices[0].message.content.strip()

                summary_lines = [line.strip() for line in summary_text.split("\n") if line.strip()]

                for old_memory in memories:
                    self._collection.delete(ids=[old_memory["id"]])
                    total_summarized += 1

                for line in summary_lines:
                    if line and len(line) > 10:
                        self.add_memory(
                            item_id=item_id,
                            content=line,
                            memory_type=m_type,
                            ttl_days=DEFAULT_MEMORY_TTL_DAYS,
                        )
                        summaries_created += 1

                logger.info(f"[VectorStore] Summarized {len(memories)} {m_type} memories into {len(summary_lines)} for item {item_id}")

            except Exception as e:
                logger.error(f"[VectorStore] Failed to summarize {m_type} memories: {e}")

        return {
            "summarized": total_summarized,
            "summaries_created": summaries_created,
            "message": f"压缩了 {total_summarized} 条记忆，生成 {summaries_created} 条摘要",
        }


vector_store = VectorStoreService()
