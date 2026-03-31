import logging
import os
import uuid
from datetime import datetime, timedelta
from typing import Any, Literal

from chromadb import Collection
from chromadb.config import Settings
import chromadb
from sentence_transformers import SentenceTransformer

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


class EmbeddingService:
    _instance: "EmbeddingService | None" = None
    _model: SentenceTransformer | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if self._model is None:
            logger.info("[Embedding] Loading all-MiniLM-L6-v2 model...")
            self._model = SentenceTransformer("all-MiniLM-L6-v2")
            logger.info("[Embedding] Model loaded successfully")

    def encode(self, texts: str | list[str]) -> list[list[float]]:
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
        if self._client is None:
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

    def add_memory(
        self,
        item_id: str,
        content: str,
        memory_type: MemoryType = "fact",
        metadata: dict[str, Any] | None = None,
        memory_id: str | None = None,
        ttl_days: int | None = None,
    ) -> str | None:
        if memory_id is None:
            memory_id = str(uuid.uuid4())

        existing = self._check_duplicate(item_id, content)
        if existing:
            logger.info(f"[VectorStore] Skipping duplicate memory for item {item_id}")
            return None

        embedding = self._embedding_service.encode_single(content)

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
        query_embedding = self._embedding_service.encode_single(content)
        
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
    ) -> list[dict[str, Any]]:
        query_embedding = self._embedding_service.encode_single(query)

        where_filter = {"item_id": item_id}
        if memory_type:
            where_filter["memory_type"] = memory_type

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where=where_filter,
        )

        memories = []
        if results["documents"] and results["documents"][0]:
            for i, doc in enumerate(results["documents"][0]):
                memory = {
                    "id": results["ids"][0][i],
                    "content": doc,
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                    "distance": results["distances"][0][i] if results["distances"] else None,
                }
                memories.append(memory)

        return memories

    def get_all_memories(
        self,
        item_id: str,
        memory_type: MemoryType | None = None,
    ) -> list[dict[str, Any]]:
        where_filter = {"item_id": item_id}
        if memory_type:
            where_filter["memory_type"] = memory_type
        
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
                except:
                    pass
        
        return stats

    def delete_memory(self, memory_id: str) -> bool:
        try:
            self._collection.delete(ids=[memory_id])
            logger.info(f"[VectorStore] Deleted memory {memory_id}")
            return True
        except Exception as e:
            logger.error(f"[VectorStore] Failed to delete memory {memory_id}: {e}")
            return False

    def delete_item_memories(self, item_id: str):
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
                except:
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
        embeddings = self._embedding_service.encode(contents)
        
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
        try:
            existing = self._collection.get(ids=[memory_id])
            if not existing["ids"]:
                return False
            
            current_meta = existing["metadatas"][0] if existing["metadatas"] else {}
            current_doc = existing["documents"][0] if existing["documents"] else ""
            
            new_content = content or current_doc
            new_meta = {**current_meta, **(metadata or {})}
            
            embedding = self._embedding_service.encode_single(new_content)
            
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
