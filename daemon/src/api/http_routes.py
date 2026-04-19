from typing import Any, Optional

import requests
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core import config
from service.file_service import FileServiceError, file_service
from service.terminal_manager import terminal_manager
from utils.logger import logger

router = APIRouter()


def verify_api_key(request: Request):
    api_key = request.headers.get("X-API-Key")
    expected_api_key = config.get("API_KEY")
    if not api_key or api_key != expected_api_key:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    return api_key


class InternalFileRequest(BaseModel):
    user_uuid: str
    path: str = "/"
    working_directory: Optional[str] = None


class InternalFileContentRequest(InternalFileRequest):
    preview_bytes: int = file_service.DEFAULT_PREVIEW_BYTES


class InternalFileWriteRequest(InternalFileRequest):
    content: str
    encoding: str = "utf-8"


class InternalRenameRequest(InternalFileRequest):
    target_path: str


def _extract_bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization", "").strip()
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return token


def _verify_file_ticket_with_backend(ticket: str, op: str) -> dict[str, Any]:
    backend_url = config.get("BACKEND_URL", "http://backend:8000")
    verify_url = f"{backend_url}/api/v1/items/file-ticket/verify"

    try:
        response = requests.post(
            verify_url,
            json={"ticket": ticket, "op": op},
            headers={"X-Daemon-Api-Key": config.get("API_KEY", "")},
            timeout=5,
        )
    except requests.exceptions.Timeout as exc:
        logger.error(f"[File] Ticket verification timed out: op={op}")
        raise HTTPException(status_code=504, detail="Ticket verification timeout") from exc
    except requests.RequestException as exc:
        logger.error(f"[File] Ticket verification failed: op={op}, error={exc}")
        raise HTTPException(status_code=502, detail="Ticket verification request failed") from exc

    if response.status_code != 200:
        detail = "Ticket verification failed"
        try:
            detail = response.json().get("detail", detail)
        except Exception:
            pass
        raise HTTPException(status_code=response.status_code, detail=detail)

    result = response.json()
    if not result.get("success"):
        raise HTTPException(status_code=401, detail=result.get("error", "Invalid file ticket"))
    return result


def _raise_file_service_error(error: FileServiceError):
    raise HTTPException(status_code=error.status_code, detail=error.message)


@router.get("/status")
async def get_daemon_status():
    return {
        "success": True,
        "version": "0.1.0",
        "status": "running",
        "terminal_count": len(terminal_manager.get_all_terminals())
    }


@router.get("/health")
async def health_check():
    return {"status": "ok"}


@router.post("/internal/items/{item_uuid}/files/tree")
async def list_item_files(
    item_uuid: str,
    payload: InternalFileRequest,
    _api_key: Any = Depends(verify_api_key),
):
    try:
        return file_service.list_directory(
            user_uuid=payload.user_uuid,
            item_uuid=item_uuid,
            path=payload.path,
            working_directory=payload.working_directory,
        )
    except FileServiceError as error:
        _raise_file_service_error(error)


@router.post("/internal/items/{item_uuid}/files/default-path")
async def get_item_default_file_path(
    item_uuid: str,
    payload: InternalFileRequest,
    _api_key: Any = Depends(verify_api_key),
):
    try:
        return file_service.get_default_directory(
            user_uuid=payload.user_uuid,
            item_uuid=item_uuid,
            working_directory=payload.working_directory,
        )
    except FileServiceError as error:
        _raise_file_service_error(error)


@router.post("/internal/items/{item_uuid}/files/content")
async def get_item_file_content(
    item_uuid: str,
    payload: InternalFileContentRequest,
    _api_key: Any = Depends(verify_api_key),
):
    try:
        return file_service.read_text_content(
            user_uuid=payload.user_uuid,
            item_uuid=item_uuid,
            path=payload.path,
            working_directory=payload.working_directory,
            preview_bytes=payload.preview_bytes,
        )
    except FileServiceError as error:
        _raise_file_service_error(error)


@router.post("/internal/items/{item_uuid}/files/write")
async def write_item_file_content(
    item_uuid: str,
    payload: InternalFileWriteRequest,
    _api_key: Any = Depends(verify_api_key),
):
    try:
        return file_service.write_text_content(
            user_uuid=payload.user_uuid,
            item_uuid=item_uuid,
            path=payload.path,
            content=payload.content,
            working_directory=payload.working_directory,
            encoding=payload.encoding,
        )
    except FileServiceError as error:
        _raise_file_service_error(error)


@router.post("/internal/items/{item_uuid}/files/mkdir")
async def create_item_directory(
    item_uuid: str,
    payload: InternalFileRequest,
    _api_key: Any = Depends(verify_api_key),
):
    try:
        return file_service.create_directory(
            user_uuid=payload.user_uuid,
            item_uuid=item_uuid,
            path=payload.path,
            working_directory=payload.working_directory,
        )
    except FileServiceError as error:
        _raise_file_service_error(error)


@router.post("/internal/items/{item_uuid}/files/rename")
async def rename_item_path(
    item_uuid: str,
    payload: InternalRenameRequest,
    _api_key: Any = Depends(verify_api_key),
):
    try:
        return file_service.rename_path(
            user_uuid=payload.user_uuid,
            item_uuid=item_uuid,
            path=payload.path,
            target_path=payload.target_path,
            working_directory=payload.working_directory,
        )
    except FileServiceError as error:
        _raise_file_service_error(error)


@router.post("/internal/items/{item_uuid}/files/delete")
async def delete_item_path(
    item_uuid: str,
    payload: InternalFileRequest,
    _api_key: Any = Depends(verify_api_key),
):
    try:
        return file_service.delete_path(
            user_uuid=payload.user_uuid,
            item_uuid=item_uuid,
            path=payload.path,
            working_directory=payload.working_directory,
        )
    except FileServiceError as error:
        _raise_file_service_error(error)


@router.post("/files/upload")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
):
    ticket = _extract_bearer_token(request)
    ticket_info = _verify_file_ticket_with_backend(ticket, "upload")

    try:
        return await file_service.save_upload(
            user_uuid=ticket_info["owner_user_id"],
            item_uuid=ticket_info["item_uuid"],
            path=ticket_info["path"],
            upload_file=file,
            working_directory=ticket_info.get("working_directory"),
            allow_overwrite=bool(ticket_info.get("allow_overwrite", False)),
        )
    except FileServiceError as error:
        _raise_file_service_error(error)


@router.get("/files/download")
async def download_file(
    request: Request,
):
    ticket = _extract_bearer_token(request)
    ticket_info = _verify_file_ticket_with_backend(ticket, "download")

    try:
        metadata = file_service.get_download_metadata(
            user_uuid=ticket_info["owner_user_id"],
            item_uuid=ticket_info["item_uuid"],
            path=ticket_info["path"],
            working_directory=ticket_info.get("working_directory"),
        )
    except FileServiceError as error:
        _raise_file_service_error(error)

    return FileResponse(
        path=str(metadata["path"]),
        filename=metadata["filename"],
        media_type=metadata["content_type"],
    )
