from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from core import config, daemon_conn_pool
from service.file_service import FileServiceError, file_service
from service.job_runner import job_runner
from service.room_manager import room_manager
from service.terminal_manager import terminal_manager
from runtime_monitor import collect_runtime_stats
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


class InternalJobRunRequest(BaseModel):
    user_uuid: str
    command: str
    working_directory: Optional[str] = None
    timeout_seconds: int = 600
    tail_lines: int = 80
    env: Optional[dict[str, str]] = None
    item_title: Optional[str] = None


class InternalJobCancelRequest(BaseModel):
    job_id: Optional[str] = None


class InternalJobResultRequest(BaseModel):
    job_id: str


def _resolve_job_context(
    item_uuid: str,
    payload_user_uuid: str,
    fallback: Optional[str],
) -> tuple[str, Optional[str]]:
    """Unify background-job cwd with the interactive terminal: when a main
    terminal is running for the item, jobs execute in the terminal's
    workdir under the terminal owner's user, so jobs and the terminal share
    one directory tree regardless of who the item owner is."""
    terminal = terminal_manager.get_terminal(item_uuid)
    if terminal is not None:
        current_workdir = terminal_manager.get_terminal_current_workdir(item_uuid)
        if current_workdir:
            return str(terminal.user_uuid), current_workdir
    return payload_user_uuid, fallback


def _require_active_main_terminal(item_uuid: str) -> None:
    status = terminal_manager.get_terminal_status(item_uuid) or {}
    if str(status.get("status") or "") not in {"running", "waiting_backend"}:
        raise HTTPException(
            status_code=409,
            detail=(
                "Main terminal is not running. Start and connect the main terminal "
                "before starting a background job."
            ),
        )
    room_connection = daemon_conn_pool.get_backend_room_listen_conn(item_uuid)
    room_socket_connected = bool(
        room_connection and room_connection.is_connected()
    )
    if (
        not room_socket_connected
        or not room_manager.has_permanent_subscribers(item_uuid)
    ):
        raise HTTPException(
            status_code=409,
            detail=(
                "Main terminal is not connected to the Backend Item Room. "
                "Start the terminal and wait for the Backend Socket Room connection "
                "before starting a background job."
            ),
        )


def _extract_bearer_token(request: Request) -> str:
    authorization = request.headers.get("Authorization", "").strip()
    if not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")

    token = authorization[7:].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Missing bearer token")
    return token


def _verify_file_ticket(ticket: str, op: str) -> dict[str, Any]:
    """HMAC 本地验票，无需回调 Backend。"""
    import base64
    import hashlib
    import hmac
    import json
    import time

    try:
        raw, signature = ticket.rsplit(".", 1)
    except ValueError:
        raise HTTPException(status_code=401, detail="Invalid ticket format")
    expected = hmac.new(
        config.get("API_KEY", "").encode(), raw.encode(), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=401, detail="Invalid ticket signature")
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw.encode()))
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid ticket payload")
    if time.time() > float(payload.get("expire_ts") or 0):
        raise HTTPException(status_code=401, detail="Ticket expired")
    if payload.get("op") != op:
        raise HTTPException(status_code=401, detail="Ticket operation mismatch")
    return {"success": True, **payload}


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


@router.get("/runtime")
async def runtime_stats(_api_key: Any = Depends(verify_api_key)):
    payload = collect_runtime_stats("daemon")
    payload["metadata"] = {
        "terminal_count": len(terminal_manager.get_all_terminals())
    }
    return payload


@router.get("/internal/items/{item_uuid}/jobs")
def list_item_jobs(
    item_uuid: str,
    _api_key: Any = Depends(verify_api_key),
):
    return job_runner.list_jobs(item_uuid=item_uuid)


@router.post("/internal/items/{item_uuid}/jobs/run")
def run_item_job(
    item_uuid: str,
    payload: InternalJobRunRequest,
    _api_key: Any = Depends(verify_api_key),
):
    logger.info(
        f"[JobHTTP] run request: item={item_uuid} user={payload.user_uuid} "
        f"timeout={payload.timeout_seconds} tail_lines={payload.tail_lines} "
        f"command={payload.command!r} cwd={payload.working_directory!r}"
    )
    if payload.item_title:
        from service.item_path_service import item_path_service

        item_path_service.register_item_title(item_uuid, payload.item_title)
    _require_active_main_terminal(item_uuid)
    job_user_uuid, working_directory = _resolve_job_context(
        item_uuid,
        payload.user_uuid,
        payload.working_directory,
    )
    result = job_runner.start_job(
        user_uuid=job_user_uuid,
        item_uuid=item_uuid,
        command=payload.command,
        working_directory=working_directory,
        timeout_seconds=payload.timeout_seconds,
        tail_lines=payload.tail_lines,
        env=payload.env,
    )
    if not result.get("success"):
        raise HTTPException(status_code=400, detail=result.get("error", "Job failed"))
    return result


@router.post("/internal/items/{item_uuid}/jobs/result")
def get_item_job_result(
    item_uuid: str,
    payload: InternalJobResultRequest,
    _api_key: Any = Depends(verify_api_key),
):
    return job_runner.get_job_result(payload.job_id)


@router.post("/internal/items/{item_uuid}/jobs/cancel")
def cancel_item_job(
    item_uuid: str,
    payload: InternalJobCancelRequest,
    _api_key: Any = Depends(verify_api_key),
):
    logger.info(
        f"[JobHTTP] cancel request: item={item_uuid} job_id={payload.job_id!r}"
    )
    return job_runner.cancel_job(item_uuid=item_uuid, job_id=payload.job_id)


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


@router.post("/internal/items/{item_uuid}/files/copy")
async def copy_item_path(
    item_uuid: str,
    payload: InternalRenameRequest,
    _api_key: Any = Depends(verify_api_key),
):
    try:
        return file_service.copy_path(
            user_uuid=payload.user_uuid,
            item_uuid=item_uuid,
            path=payload.path,
            target_path=payload.target_path,
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
    ticket_info = _verify_file_ticket(ticket, "upload")

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
    ticket_info = _verify_file_ticket(ticket, "download")

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
