import uuid
from typing import Any

from fastapi import APIRouter, HTTPException, Depends, Request, UploadFile, File
from fastapi.responses import FileResponse

from core import memory_store, config
from service.terminal_manager import terminal_manager
from utils.logger import logger

router = APIRouter()


def verify_api_key(request: Request):
    api_key = request.headers.get("X-API-Key")
    expected_api_key = config.get("API_KEY")
    if not api_key or api_key != expected_api_key:
        raise HTTPException(status_code=401, detail="Invalid API Key")


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


@router.post("/file/upload")
async def upload_file(
    file: UploadFile = File(...),
    api_key: Any = Depends(verify_api_key)
):
    pass


@router.get("/file/download")
async def download_file(
    path: str,
    api_key: Any = Depends(verify_api_key)
):
    pass
