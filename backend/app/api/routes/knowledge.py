from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlmodel import select

from app.api.deps import CurrentUser, SessionDep
from app.models import ItemHandler, Message
from app.services.agent.agent import agent_manager
from app.services.agent.knowledge import knowledge_base_service

router = APIRouter(prefix="/knowledge", tags=["knowledge"])


class KnowledgeFileItem(BaseModel):
    path: str
    name: str
    size: int | None = None
    modified_at: int | None = None
    enabled: bool
    indexed: bool
    missing: bool
    chunk_count: int


class KnowledgeFileListResponse(BaseModel):
    data: list[KnowledgeFileItem]
    count: int
    enabled_count: int


class KnowledgeUploadResponse(BaseModel):
    uploaded: list[KnowledgeFileItem]
    count: int


def _prune_deleted_file_from_handlers(
    session: SessionDep,
    *,
    file_path: str,
) -> int:
    handlers = session.exec(select(ItemHandler)).all()
    updated_count = 0

    for handler in handlers:
        enabled_files = handler.enabled_knowledge_files or []
        if file_path not in enabled_files:
            continue

        handler.enabled_knowledge_files = [
            path for path in enabled_files if path != file_path
        ]
        session.add(handler)
        updated_count += 1

    if updated_count:
        session.commit()
        for handler in handlers:
            if handler.enabled_knowledge_files is not None:
                agent_manager.refresh_cached(handler)

    return updated_count


@router.get("/files", response_model=KnowledgeFileListResponse)
def list_knowledge_files(_current_user: CurrentUser) -> KnowledgeFileListResponse:
    files = [
        KnowledgeFileItem.model_validate(item)
        for item in knowledge_base_service.list_files()
    ]
    return KnowledgeFileListResponse(
        data=files,
        count=len(files),
        enabled_count=0,
    )


@router.post("/files/upload", response_model=KnowledgeUploadResponse)
async def upload_knowledge_files(
    _current_user: CurrentUser,
    files: list[UploadFile] = File(...),
) -> KnowledgeUploadResponse:
    uploaded_items: list[KnowledgeFileItem] = []
    saved_paths: list[str] = []

    for upload in files:
        if not upload.filename:
            raise HTTPException(status_code=400, detail="File name is required")

        content = await upload.read()
        try:
            saved = knowledge_base_service.save_file_bytes(
                upload.filename,
                content,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        saved_paths.append(saved["path"])

    knowledge_base_service.sync_library()

    listed_files = {
        entry["path"]: entry
        for entry in knowledge_base_service.list_files(sync=False)
    }

    for file_path in saved_paths:
        uploaded_item = listed_files.get(file_path)
        if uploaded_item is None:
            uploaded_item = {
                "path": file_path,
                "name": file_path.split("/")[-1],
                "size": None,
                "modified_at": None,
                "enabled": False,
                "indexed": False,
                "missing": False,
                "chunk_count": 0,
            }
        uploaded_items.append(KnowledgeFileItem.model_validate(uploaded_item))

    return KnowledgeUploadResponse(uploaded=uploaded_items, count=len(uploaded_items))


@router.get("/files/download/{file_path:path}")
def download_knowledge_file(
    _current_user: CurrentUser,
    file_path: str,
) -> FileResponse:
    try:
        absolute_path = knowledge_base_service.get_file_absolute_path(file_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="Knowledge file not found") from exc

    return FileResponse(
        path=absolute_path,
        filename=absolute_path.name,
        media_type="application/octet-stream",
    )


@router.delete("/files/{file_path:path}")
def delete_knowledge_file(
    session: SessionDep,
    _current_user: CurrentUser,
    file_path: str,
) -> Message:
    try:
        normalized_path = knowledge_base_service.normalize_relative_path(file_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    deleted = knowledge_base_service.delete_file(normalized_path)
    if not deleted:
        raise HTTPException(status_code=404, detail="Knowledge file not found")

    _prune_deleted_file_from_handlers(session, file_path=normalized_path)
    return Message(message="Knowledge file deleted successfully")
