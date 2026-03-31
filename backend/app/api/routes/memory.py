import logging
import uuid
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.api.deps import CurrentUser, SessionDep
from app.models import Item, ItemChatSession, ItemChatSessionPublic
from app.services.agent.memory.vector_store import (
    vector_store,
    MemoryType,
    MEMORY_TYPES,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class MemoryCreate(BaseModel):
    content: str
    memory_type: MemoryType = "fact"
    metadata: dict[str, Any] | None = None
    ttl_days: int | None = None


class MemoryUpdate(BaseModel):
    content: str | None = None
    metadata: dict[str, Any] | None = None


class MemorySearch(BaseModel):
    query: str
    n_results: int = 5
    memory_type: MemoryType | None = None


@router.get("/{item_id}/session", response_model=ItemChatSessionPublic)
def get_chat_session(
    item_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    if not current_user.is_superuser and item.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    chat_session = session.exec(
        select(ItemChatSession).where(ItemChatSession.item_id == item_id)
    ).first()
    
    if not chat_session:
        chat_session = ItemChatSession(item_id=item_id, messages=[])
        session.add(chat_session)
        session.commit()
        session.refresh(chat_session)
    
    return chat_session


@router.post("/{item_id}/session", response_model=ItemChatSessionPublic)
def save_chat_session(
    item_id: uuid.UUID,
    messages: list[dict],
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    if not current_user.is_superuser and item.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    chat_session = session.exec(
        select(ItemChatSession).where(ItemChatSession.item_id == item_id)
    ).first()
    
    if not chat_session:
        chat_session = ItemChatSession(item_id=item_id, messages=messages)
        session.add(chat_session)
    else:
        chat_session.messages = messages
    
    session.commit()
    session.refresh(chat_session)
    
    return chat_session


@router.delete("/{item_id}/session")
def clear_chat_session(
    item_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    if not current_user.is_superuser and item.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    chat_session = session.exec(
        select(ItemChatSession).where(ItemChatSession.item_id == item_id)
    ).first()
    
    if chat_session:
        chat_session.messages = []
        session.commit()
    
    return {"message": "Chat session cleared"}


@router.delete("/{item_id}/all")
def clear_all_session_data(
    item_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    if not current_user.is_superuser and item.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    results = {}
    
    chat_session = session.exec(
        select(ItemChatSession).where(ItemChatSession.item_id == item_id)
    ).first()
    if chat_session:
        chat_session.messages = []
        session.commit()
        results["chat_session"] = "cleared"
    
    try:
        vector_store.delete_item_memories(str(item_id))
        results["memories"] = "cleared"
    except Exception as e:
        logger.error(f"Failed to clear memories: {e}")
        results["memories"] = f"error: {e}"
    
    try:
        from app.services.log_manager import LogManager
        LogManager().delete_log(str(item.owner_id), str(item_id))
        results["terminal_log"] = "cleared"
    except Exception as e:
        logger.error(f"Failed to clear terminal log: {e}")
        results["terminal_log"] = f"error: {e}"
    
    logger.info(f"[Memory] Cleared all session data for item {item_id}: {results}")
    return {"message": "All session data cleared", "details": results}


@router.get("/{item_id}/memories")
def get_all_memories(
    item_id: uuid.UUID,
    memory_type: MemoryType | None = None,
    session: SessionDep = None,
    current_user: CurrentUser = None,
) -> Any:
    memories = vector_store.get_all_memories(
        item_id=str(item_id),
        memory_type=memory_type,
    )
    return {"memories": memories, "count": len(memories)}


@router.get("/{item_id}/memories/stats")
def get_memory_stats(
    item_id: uuid.UUID,
    session: SessionDep = None,
    current_user: CurrentUser = None,
) -> Any:
    stats = vector_store.get_memory_stats(str(item_id))
    stats["memory_types"] = MEMORY_TYPES
    return stats


@router.get("/{item_id}/memories/types")
def get_memory_types() -> Any:
    return {"types": MEMORY_TYPES}


@router.post("/{item_id}/memories/search")
def search_memories(
    item_id: uuid.UUID,
    request: MemorySearch,
    session: SessionDep = None,
    current_user: CurrentUser = None,
) -> Any:
    memories = vector_store.search_memories(
        item_id=str(item_id),
        query=request.query,
        n_results=request.n_results,
        memory_type=request.memory_type,
    )
    
    return {"memories": memories}


@router.post("/{item_id}/memories")
def add_memory(
    item_id: uuid.UUID,
    request: MemoryCreate,
    session: SessionDep = None,
    current_user: CurrentUser = None,
) -> Any:
    memory_id = vector_store.add_memory(
        item_id=str(item_id),
        content=request.content,
        memory_type=request.memory_type,
        metadata=request.metadata,
        ttl_days=request.ttl_days,
    )
    
    if memory_id is None:
        return {"memory_id": None, "message": "Duplicate memory skipped"}
    
    return {"memory_id": memory_id, "message": "Memory added"}


@router.put("/{item_id}/memories/{memory_id}")
def update_memory(
    item_id: uuid.UUID,
    memory_id: str,
    request: MemoryUpdate,
    session: SessionDep = None,
    current_user: CurrentUser = None,
) -> Any:
    success = vector_store.update_memory(
        memory_id=memory_id,
        content=request.content,
        metadata=request.metadata,
    )
    
    if not success:
        raise HTTPException(status_code=404, detail="Memory not found")
    
    return {"message": "Memory updated"}


@router.delete("/{item_id}/memories/{memory_id}")
def delete_memory(
    item_id: uuid.UUID,
    memory_id: str,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    if not current_user.is_superuser and item.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    vector_store.delete_memory(memory_id)
    return {"message": "Memory deleted"}


@router.delete("/{item_id}/memories")
def clear_memories(
    item_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    if not current_user.is_superuser and item.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    vector_store.delete_item_memories(str(item_id))
    return {"message": "All memories cleared"}


@router.post("/{item_id}/memories/expire")
def expire_memories(
    item_id: uuid.UUID,
    session: SessionDep = None,
    current_user: CurrentUser = None,
) -> Any:
    count = vector_store.expire_old_memories(str(item_id))
    return {"message": f"Expired {count} memories", "count": count}


@router.post("/{item_id}/memories/deduplicate")
def deduplicate_memories(
    item_id: uuid.UUID,
    session: SessionDep = None,
    current_user: CurrentUser = None,
) -> Any:
    count = vector_store.deduplicate_memories(str(item_id))
    return {"message": f"Deduplicated {count} memories", "count": count}


@router.post("/{item_id}/memories/summarize")
def summarize_memories(
    item_id: uuid.UUID,
    threshold: int = 10,
    session: SessionDep = None,
    current_user: CurrentUser = None,
) -> Any:
    from app.services.agent.agent import agent_manager
    from sqlmodel import select
    from app.models import Item, ItemHandler, ItemHandlerItem
    
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    
    handler_item = session.exec(
        select(ItemHandlerItem).where(ItemHandlerItem.item_id == item_id)
    ).first()
    
    if not handler_item:
        raise HTTPException(status_code=404, detail="No handler associated with this item")
    
    handler = session.get(ItemHandler, handler_item.item_handler_id)
    if not handler:
        raise HTTPException(status_code=404, detail="Handler not found")
    
    result = vector_store.summarize_memories(
        item_id=str(item_id),
        model=handler.model or "deepseek/deepseek-chat",
        api_key=handler.api_key,
        api_base=handler.api_url,
        threshold=threshold,
    )
    
    return result
