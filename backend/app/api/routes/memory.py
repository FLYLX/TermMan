import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from sqlmodel import Session, select

from app.api.deps import CurrentUser, SessionDep
from app.models import Item, ItemChatSession, ItemChatSessionPublic
from app.services.agent.memory.vector_store import (
    MEMORY_TYPES,
    vector_store,
)
from app.services.agent.prompts.policy import (
    build_manual_status_update,
    get_allowed_memory_statuses,
    resolve_memory_status,
)

logger = logging.getLogger(__name__)

router = APIRouter()
LongTermMemoryType = Literal["fact", "preference", "error", "context"]
STATUS_MEMORY_TYPES = {"error"}
INACTIVE_MEMORY_STATUSES = {"resolved"}


class MemoryCreate(BaseModel):
    content: str
    memory_type: LongTermMemoryType = "fact"
    metadata: dict[str, Any] | None = None
    ttl_days: int | None = None


class MemoryUpdate(BaseModel):
    content: str | None = None
    metadata: dict[str, Any] | None = None


class MemorySearch(BaseModel):
    query: str
    n_results: int = 5
    memory_type: LongTermMemoryType | None = None


class MemoryStatusUpdate(BaseModel):
    status: Literal["active", "resolved"]


class InstalledSoftwareUpsert(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    manager: str = Field(default="unknown", max_length=64)
    version: str | None = Field(default=None, max_length=120)
    command: str | None = Field(default=None, max_length=500)
    notes: str | None = Field(default=None, max_length=500)


class InstalledSoftwareDelete(BaseModel):
    name: str = Field(..., min_length=1, max_length=160)
    manager: str | None = Field(default=None, max_length=64)
    reason: str | None = Field(default=None, max_length=500)


class ScheduledTaskUpsert(BaseModel):
    task_id: str | None = Field(default=None, max_length=80)
    name: str = Field(..., min_length=1, max_length=160)
    instruction: str = Field(..., min_length=1, max_length=4000)
    schedule_type: Literal["once", "interval", "daily"]
    run_at: str | None = Field(default=None, max_length=80)
    interval_seconds: int | None = Field(default=None, ge=10, le=31_536_000)
    time_of_day: str | None = Field(default=None, max_length=16)
    timezone: str = Field(default="Asia/Shanghai", max_length=80)
    enabled: bool = True

class ItemChatSessionPage(ItemChatSessionPublic):
    total: int = 0
    offset: int = 0
    limit: int | None = None
    has_more: bool = False


MAX_MEMORY_IMPORT_ITEMS = 1000


class MemoryExportItem(BaseModel):
    id: str | None = None
    content: str = Field(..., min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryImportRequest(BaseModel):
    version: int | None = None
    memories: list[MemoryExportItem] = Field(
        ...,
        min_length=1,
        max_length=MAX_MEMORY_IMPORT_ITEMS,
    )


def _get_accessible_item(
    item_id: uuid.UUID,
    session: Session,
    current_user: CurrentUser,
) -> Item:
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")

    if not current_user.is_superuser and item.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")

    return item


def _memory_status_bucket(memory: dict[str, Any]) -> int:
    metadata = memory.get("metadata") or {}
    memory_type = str(metadata.get("memory_type") or "")
    status = str(resolve_memory_status(memory) or "").lower()
    if memory_type in STATUS_MEMORY_TYPES:
        if status and status not in INACTIVE_MEMORY_STATUSES:
            return 0
        if status in INACTIVE_MEMORY_STATUSES:
            return 2
    return 1


def _memory_timestamp_sort_value(memory: dict[str, Any]) -> str:
    metadata = memory.get("metadata") or {}
    return str(metadata.get("updated_at") or metadata.get("created_at") or "")


def _sort_memories(memories: list[dict[str, Any]]) -> list[dict[str, Any]]:
    timestamp_sorted = sorted(
        memories,
        key=_memory_timestamp_sort_value,
        reverse=True,
    )
    return sorted(
        timestamp_sorted,
        key=_memory_status_bucket,
    )


def _filter_memories_by_status(
    memories: list[dict[str, Any]],
    memory_status: str | None,
) -> list[dict[str, Any]]:
    if not memory_status:
        return memories
    return [
        memory
        for memory in memories
        if str(resolve_memory_status(memory) or "").lower() == memory_status
    ]


def _build_status_counts(memories: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    counts: dict[str, dict[str, int]] = {
        "error": {"active": 0, "resolved": 0},
    }

    for memory in memories:
        metadata = memory.get("metadata") or {}
        memory_type = str(metadata.get("memory_type") or "")
        status = str(resolve_memory_status(memory) or "").lower()
        if memory_type == "error":
            if status == "resolved":
                counts["error"]["resolved"] += 1
            else:
                counts["error"]["active"] += 1

    return counts


def _get_item_memory_or_404(item_id: uuid.UUID, memory_id: str) -> dict[str, Any]:
    memory = vector_store.get_memory(memory_id)
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    memory_item_id = str((memory.get("metadata") or {}).get("item_id") or "")
    if memory_item_id != str(item_id):
        raise HTTPException(status_code=404, detail="Memory not found")

    return memory


def _coerce_memory_type(value: Any) -> LongTermMemoryType:
    memory_type = str(value or "fact")
    if memory_type == "task":
        return "context"
    if memory_type not in MEMORY_TYPES:
        return "fact"
    return memory_type  # type: ignore[return-value]


def _is_visible_long_term_memory(memory: dict[str, Any]) -> bool:
    memory_type = str((memory.get("metadata") or {}).get("memory_type") or "fact")
    return memory_type in MEMORY_TYPES


def _visible_long_term_memories(
    memories: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [memory for memory in memories if _is_visible_long_term_memory(memory)]


def _visible_memory_stats(memories: list[dict[str, Any]]) -> dict[str, Any]:
    now = datetime.now()
    by_type = dict.fromkeys(MEMORY_TYPES, 0)
    expired_count = 0
    for memory in memories:
        metadata = memory.get("metadata") or {}
        memory_type = str(metadata.get("memory_type") or "fact")
        if memory_type not in MEMORY_TYPES:
            continue
        by_type[memory_type] += 1
        if memory_type in {"preference", "error"}:
            continue
        expires_at = metadata.get("expires_at")
        if not expires_at:
            continue
        try:
            parsed = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        except ValueError:
            continue
        current = datetime.now(parsed.tzinfo) if parsed.tzinfo else now
        if parsed < current:
            expired_count += 1
    return {
        "total": len(memories),
        "by_type": by_type,
        "expired_count": expired_count,
    }


def _sanitize_import_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    clean_metadata: dict[str, Any] = {}
    for key, value in dict(metadata or {}).items():
        if key in {"item_id", "memory_type", "distance"}:
            continue
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            clean_metadata[key] = value
        else:
            clean_metadata[key] = str(value)
    return clean_metadata


@router.get("/{item_id}/session", response_model=ItemChatSessionPage)
def get_chat_session(
    item_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> Any:
    _get_accessible_item(item_id, session, current_user)

    chat_session = session.exec(
        select(ItemChatSession).where(ItemChatSession.item_id == item_id)
    ).first()

    if not chat_session:
        chat_session = ItemChatSession(item_id=item_id, messages=[])
        session.add(chat_session)
        session.commit()
        session.refresh(chat_session)

    all_messages = list(chat_session.messages or [])
    total = len(all_messages)
    if limit is None:
        page_messages = all_messages
        effective_offset = 0
        effective_limit = total
        has_more = False
    else:
        effective_offset = min(offset, total)
        end = max(total - effective_offset, 0)
        start = max(end - limit, 0)
        page_messages = all_messages[start:end]
        effective_limit = limit
        has_more = start > 0

    return ItemChatSessionPage(
        id=chat_session.id,
        item_id=chat_session.item_id,
        created_at=chat_session.created_at,
        updated_at=chat_session.updated_at,
        messages=page_messages,
        total=total,
        offset=effective_offset,
        limit=effective_limit,
        has_more=has_more,
    )


@router.post("/{item_id}/session", response_model=ItemChatSessionPublic)
def save_chat_session(
    item_id: uuid.UUID,
    messages: list[dict],
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    _get_accessible_item(item_id, session, current_user)

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
    _get_accessible_item(item_id, session, current_user)

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
    item = _get_accessible_item(item_id, session, current_user)

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


@router.get("/{item_id}/installed-software")
def get_installed_software(
    item_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    _get_accessible_item(item_id, session, current_user)

    from app.services.agent.installed_software import list_installed_software

    items = list_installed_software(str(item_id))
    return {"items": items, "count": len(items)}


@router.post("/{item_id}/installed-software")
def upsert_installed_software(
    item_id: uuid.UUID,
    request: InstalledSoftwareUpsert,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    _get_accessible_item(item_id, session, current_user)

    from app.services.agent.installed_software import record_installed_software

    item = record_installed_software(
        str(item_id),
        name=request.name,
        manager=request.manager or "unknown",
        version=request.version or "",
        command=request.command or "",
        notes=request.notes or "",
    )
    return {"item": item, "message": "Installed software saved"}


@router.delete("/{item_id}/installed-software")
def delete_installed_software(
    item_id: uuid.UUID,
    request: InstalledSoftwareDelete,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    _get_accessible_item(item_id, session, current_user)

    from app.services.agent.installed_software import remove_installed_software

    result = remove_installed_software(
        str(item_id),
        name=request.name,
        manager=request.manager or "",
        reason=request.reason or "manual edit",
    )
    if result.get("count", 0) <= 0:
        raise HTTPException(status_code=404, detail="Installed software record not found")
    return {"message": "Installed software removed", **result}


@router.get("/{item_id}/scheduled-tasks")
def get_scheduled_tasks(
    item_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    _get_accessible_item(item_id, session, current_user)

    from app.services.agent.scheduled_tasks import list_scheduled_tasks

    tasks = list_scheduled_tasks(str(item_id))
    return {"items": tasks, "count": len(tasks)}


@router.post("/{item_id}/scheduled-tasks")
def upsert_scheduled_task(
    item_id: uuid.UUID,
    request: ScheduledTaskUpsert,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    _get_accessible_item(item_id, session, current_user)

    from app.services.agent.scheduled_tasks import write_scheduled_task

    try:
        task = write_scheduled_task(
            str(item_id),
            task_id=request.task_id or "",
            name=request.name,
            instruction=request.instruction,
            schedule_type=request.schedule_type,
            run_at=request.run_at or "",
            interval_seconds=request.interval_seconds or 0,
            time_of_day=request.time_of_day or "",
            timezone_name=request.timezone,
            enabled=request.enabled,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc.args[0])) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"item": task, "message": "Scheduled task saved"}


@router.delete("/{item_id}/scheduled-tasks/{task_id}")
def remove_scheduled_task(
    item_id: uuid.UUID,
    task_id: str,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    _get_accessible_item(item_id, session, current_user)

    from app.services.agent.scheduled_tasks import delete_scheduled_task

    result = delete_scheduled_task(
        str(item_id),
        task_id=task_id,
        reason="manual delete",
    )
    if result.get("count", 0) <= 0:
        raise HTTPException(status_code=404, detail="Scheduled task not found")
    return {"message": "Scheduled task deleted", **result}

@router.get("/{item_id}/memories")
def get_all_memories(
    item_id: uuid.UUID,
    memory_type: LongTermMemoryType | None = None,
    memory_status: Literal["active", "completed", "resolved"] | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(10, ge=1, le=200),
    session: SessionDep = None,
    current_user: CurrentUser = None,
) -> Any:
    _get_accessible_item(item_id, session, current_user)

    memories = vector_store.get_all_memories(
        item_id=str(item_id),
        memory_type=memory_type,
    )
    filtered_memories = _filter_memories_by_status(
        _visible_long_term_memories(memories),
        memory_status,
    )
    sorted_memories = _sort_memories(filtered_memories)
    page_memories = sorted_memories[offset : offset + limit]
    return {
        "memories": page_memories,
        "count": len(sorted_memories),
        "offset": offset,
        "limit": limit,
        "has_more": offset + len(page_memories) < len(sorted_memories),
    }


@router.get("/{item_id}/memories/export")
def export_memories(
    item_id: uuid.UUID,
    memory_type: LongTermMemoryType | None = None,
    session: SessionDep = None,
    current_user: CurrentUser = None,
) -> Any:
    _get_accessible_item(item_id, session, current_user)

    memories = vector_store.get_all_memories(
        item_id=str(item_id),
        memory_type=memory_type,
    )
    sorted_memories = _sort_memories(_visible_long_term_memories(memories))
    return {
        "version": 1,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "item_id": str(item_id),
        "count": len(sorted_memories),
        "memories": sorted_memories,
    }


@router.post("/{item_id}/memories/import")
def import_memories(
    item_id: uuid.UUID,
    request: MemoryImportRequest,
    session: SessionDep = None,
    current_user: CurrentUser = None,
) -> Any:
    _get_accessible_item(item_id, session, current_user)

    imported_ids: list[str] = []
    skipped = 0
    errors: list[str] = []
    imported_at = datetime.now(timezone.utc).isoformat()

    for index, memory in enumerate(request.memories):
        content = memory.content.strip()
        if not content:
            skipped += 1
            errors.append(f"memories[{index}]: empty content")
            continue

        metadata = _sanitize_import_metadata(memory.metadata)
        metadata["imported_at"] = imported_at
        if memory.id:
            metadata["imported_from_memory_id"] = memory.id
        raw_memory_type = str(memory.metadata.get("memory_type") or "fact")
        try:
            memory_id = vector_store.add_memory(
                item_id=str(item_id),
                content=content,
                memory_type=_coerce_memory_type(raw_memory_type),
                metadata=metadata,
                allow_duplicate=True,
            )
        except Exception as e:
            logger.warning("[Memory] Failed to import memory %s: %s", index, e)
            skipped += 1
            errors.append(f"memories[{index}]: {e}")
            continue

        if memory_id is None:
            skipped += 1
            continue
        imported_ids.append(memory_id)

    return {
        "message": f"Imported {len(imported_ids)} memories",
        "imported": len(imported_ids),
        "skipped": skipped,
        "errors": errors,
        "memory_ids": imported_ids,
    }


@router.get("/{item_id}/memories/stats")
def get_memory_stats(
    item_id: uuid.UUID,
    session: SessionDep = None,
    current_user: CurrentUser = None,
) -> Any:
    _get_accessible_item(item_id, session, current_user)

    memories = _visible_long_term_memories(
        vector_store.get_all_memories(str(item_id))
    )
    stats = _visible_memory_stats(memories)
    stats["memory_types"] = MEMORY_TYPES
    stats["status_counts"] = _build_status_counts(memories)
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
    _get_accessible_item(item_id, session, current_user)

    memories = vector_store.search_memories(
        item_id=str(item_id),
        query=request.query,
        n_results=request.n_results,
        memory_type=request.memory_type,
        include_expired=True,
        active_only=False,
    )

    return {"memories": _sort_memories(_visible_long_term_memories(memories))}


@router.post("/{item_id}/memories")
def add_memory(
    item_id: uuid.UUID,
    request: MemoryCreate,
    session: SessionDep = None,
    current_user: CurrentUser = None,
) -> Any:
    _get_accessible_item(item_id, session, current_user)

    memory_id = vector_store.add_memory(
        item_id=str(item_id),
        content=request.content,
        memory_type=request.memory_type,
        metadata=request.metadata,
        ttl_days=request.ttl_days,
        allow_duplicate=True,
    )

    if memory_id is None:
        return {"memory_id": None, "message": "Memory was not saved"}

    return {"memory_id": memory_id, "message": "Memory added"}


@router.put("/{item_id}/memories/{memory_id}")
def update_memory(
    item_id: uuid.UUID,
    memory_id: str,
    request: MemoryUpdate,
    session: SessionDep = None,
    current_user: CurrentUser = None,
) -> Any:
    _get_accessible_item(item_id, session, current_user)

    success = vector_store.update_memory(
        memory_id=memory_id,
        content=request.content,
        metadata=request.metadata,
    )

    if not success:
        raise HTTPException(status_code=404, detail="Memory not found")

    return {"message": "Memory updated"}


@router.post("/{item_id}/memories/{memory_id}/status")
def update_memory_status(
    item_id: uuid.UUID,
    memory_id: str,
    request: MemoryStatusUpdate,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    _get_accessible_item(item_id, session, current_user)
    memory = _get_item_memory_or_404(item_id, memory_id)

    memory_type = str((memory.get("metadata") or {}).get("memory_type") or "")
    if memory_type not in MEMORY_TYPES:
        raise HTTPException(
            status_code=400,
            detail="Task state belongs to the task queue, not long-term memory",
        )
    allowed_statuses = get_allowed_memory_statuses(memory_type)
    if request.status not in allowed_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Status '{request.status}' is not valid for memory type '{memory_type}'",
        )

    update_payload = build_manual_status_update(memory, request.status)
    if update_payload is None:
        raise HTTPException(status_code=400, detail="Invalid memory status transition")

    updated_content, updated_metadata = update_payload
    success = vector_store.update_memory(
        memory_id=memory_id,
        content=updated_content,
        metadata=updated_metadata,
    )
    if not success:
        raise HTTPException(status_code=404, detail="Memory not found")

    return {
        "message": "Memory status updated",
        "memory": {
            "id": memory_id,
            "content": updated_content,
            "metadata": updated_metadata,
        },
    }


@router.delete("/{item_id}/memories/{memory_id}")
def delete_memory(
    item_id: uuid.UUID,
    memory_id: str,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    _get_accessible_item(item_id, session, current_user)
    _get_item_memory_or_404(item_id, memory_id)

    vector_store.delete_memory(memory_id)
    return {"message": "Memory deleted"}


@router.delete("/{item_id}/memories")
def clear_memories(
    item_id: uuid.UUID,
    session: SessionDep,
    current_user: CurrentUser,
) -> Any:
    _get_accessible_item(item_id, session, current_user)

    vector_store.delete_item_memories(str(item_id))
    return {"message": "All memories cleared"}


@router.post("/{item_id}/memories/expire")
def expire_memories(
    item_id: uuid.UUID,
    session: SessionDep = None,
    current_user: CurrentUser = None,
) -> Any:
    _get_accessible_item(item_id, session, current_user)

    count = vector_store.expire_old_memories(str(item_id))
    return {"message": f"Expired {count} memories", "count": count}


@router.post("/{item_id}/memories/deduplicate")
def deduplicate_memories(
    item_id: uuid.UUID,
    session: SessionDep = None,
    current_user: CurrentUser = None,
) -> Any:
    _get_accessible_item(item_id, session, current_user)

    count = vector_store.deduplicate_memories(str(item_id))
    return {"message": f"Deduplicated {count} memories", "count": count}


@router.post("/{item_id}/memories/summarize")
def summarize_memories(
    item_id: uuid.UUID,
    threshold: int = 10,
    session: SessionDep = None,
    current_user: CurrentUser = None,
) -> Any:
    _get_accessible_item(item_id, session, current_user)

    result = vector_store.summarize_memories(
        item_id=str(item_id),
        threshold=threshold,
    )

    return result
