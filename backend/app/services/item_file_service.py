import logging
from typing import Any

import httpx

from app.core.config import settings
from app.models import Item

from .auth_service import auth_service

logger = logging.getLogger(__name__)


class ItemFileServiceError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class ItemFileService:
    DEFAULT_PREVIEW_BYTES = 256 * 1024

    def get_default_path(self, *, item: Item) -> dict[str, Any]:
        payload = {
            "user_uuid": str(item.owner_id),
            "path": "/",
            "working_directory": item.working_directory,
        }
        return self._post_internal(
            item,
            f"/api/internal/items/{item.id}/files/default-path",
            json=payload,
        )

    def list_tree(self, *, item: Item, path: str = "/") -> dict[str, Any]:
        payload = {
            "user_uuid": str(item.owner_id),
            "path": self._normalize_path(path, allow_root=True),
            "working_directory": item.working_directory,
        }
        return self._post_internal(item, f"/api/internal/items/{item.id}/files/tree", json=payload)

    def get_content(
        self,
        *,
        item: Item,
        path: str,
        preview_bytes: int = DEFAULT_PREVIEW_BYTES,
    ) -> dict[str, Any]:
        payload = {
            "user_uuid": str(item.owner_id),
            "path": self._normalize_path(path, allow_root=False),
            "working_directory": item.working_directory,
            "preview_bytes": preview_bytes,
        }
        return self._post_internal(item, f"/api/internal/items/{item.id}/files/content", json=payload)

    def write_content(
        self,
        *,
        item: Item,
        path: str,
        content: str,
        encoding: str = "utf-8",
    ) -> dict[str, Any]:
        payload = {
            "user_uuid": str(item.owner_id),
            "path": self._normalize_path(path, allow_root=False),
            "working_directory": item.working_directory,
            "content": content,
            "encoding": encoding or "utf-8",
        }
        return self._post_internal(item, f"/api/internal/items/{item.id}/files/write", json=payload)

    def create_directory(self, *, item: Item, path: str) -> dict[str, Any]:
        payload = {
            "user_uuid": str(item.owner_id),
            "path": self._normalize_path(path, allow_root=False),
            "working_directory": item.working_directory,
        }
        return self._post_internal(item, f"/api/internal/items/{item.id}/files/mkdir", json=payload)

    def rename_path(self, *, item: Item, path: str, target_path: str) -> dict[str, Any]:
        payload = {
            "user_uuid": str(item.owner_id),
            "path": self._normalize_path(path, allow_root=False),
            "target_path": self._normalize_path(target_path, allow_root=False),
            "working_directory": item.working_directory,
        }
        return self._post_internal(item, f"/api/internal/items/{item.id}/files/rename", json=payload)

    def delete_path(self, *, item: Item, path: str) -> dict[str, Any]:
        payload = {
            "user_uuid": str(item.owner_id),
            "path": self._normalize_path(path, allow_root=False),
            "working_directory": item.working_directory,
        }
        return self._post_internal(item, f"/api/internal/items/{item.id}/files/delete", json=payload)

    def issue_download_ticket(self, *, item: Item, actor_user_id: str, path: str) -> dict[str, Any]:
        normalized_path = self._normalize_path(path, allow_root=False)
        ticket_info = auth_service.generate_file_ticket(
            item_uuid=str(item.id),
            actor_user_id=actor_user_id,
            owner_user_id=str(item.owner_id),
            daemon_api_key=item.api_key or "",
            op="download",
            path=normalized_path,
            working_directory=item.working_directory,
        )
        return {
            "success": True,
            "ticket": ticket_info["ticket"],
            "expires_in": ticket_info["expires_in"],
            "item_uuid": str(item.id),
            "path": normalized_path,
            "daemon_url": self._daemon_public_base_url(item),
            "url": f"{self._daemon_public_base_url(item)}/api/files/download",
        }

    def issue_upload_ticket(
        self,
        *,
        item: Item,
        actor_user_id: str,
        path: str,
        allow_overwrite: bool = False,
    ) -> dict[str, Any]:
        normalized_path = self._normalize_path(path, allow_root=False)
        ticket_info = auth_service.generate_file_ticket(
            item_uuid=str(item.id),
            actor_user_id=actor_user_id,
            owner_user_id=str(item.owner_id),
            daemon_api_key=item.api_key or "",
            op="upload",
            path=normalized_path,
            working_directory=item.working_directory,
            allow_overwrite=allow_overwrite,
        )
        return {
            "success": True,
            "ticket": ticket_info["ticket"],
            "expires_in": ticket_info["expires_in"],
            "item_uuid": str(item.id),
            "path": normalized_path,
            "allow_overwrite": allow_overwrite,
            "daemon_url": self._daemon_public_base_url(item),
            "url": f"{self._daemon_public_base_url(item)}/api/files/upload",
        }

    def _post_internal(self, item: Item, route_path: str, json: dict[str, Any]) -> dict[str, Any]:
        self._ensure_daemon_configured(item)
        url = f"{self._daemon_base_url(item)}{route_path}"
        headers = {"X-API-Key": item.api_key or ""}

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(url, json=json, headers=headers)
        except httpx.TimeoutException as exc:
            logger.error("Daemon file request timed out: %s", url)
            raise ItemFileServiceError("Daemon request timed out", status_code=504) from exc
        except httpx.HTTPError as exc:
            logger.error("Daemon file request failed: %s, error=%s", url, exc)
            raise ItemFileServiceError("Daemon request failed", status_code=502) from exc

        return self._parse_json_response(response)

    @staticmethod
    def _parse_json_response(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise ItemFileServiceError("Invalid response from daemon", status_code=502) from exc

        if response.status_code >= 400:
            raise ItemFileServiceError(
                payload.get("detail", "Daemon file request failed"),
                status_code=response.status_code,
            )
        return payload

    @staticmethod
    def _normalize_path(path: str, *, allow_root: bool) -> str:
        normalized = (path or "").replace("\\", "/").strip()
        if normalized in {"", ".", "/"}:
            if allow_root:
                return "/"
            raise ItemFileServiceError("Path is required")
        return normalized.lstrip("/")

    @staticmethod
    def _daemon_base_url(item: Item) -> str:
        return f"http://{item.socket_host}:{item.socket_port}"

    @staticmethod
    def _daemon_public_base_url(item: Item) -> str:
        public_url = (settings.DAEMON_PUBLIC_URL or "").strip().rstrip("/")
        if public_url:
            return public_url
        host = (settings.DAEMON_PUBLIC_HOST or "").strip() or "localhost"
        port = settings.DAEMON_PUBLIC_PORT or settings.DAEMON_HOST_PORT or item.socket_port or 9000
        return f"http://{host}:{port}"

    @staticmethod
    def _ensure_daemon_configured(item: Item):
        if not item.socket_host or not item.socket_port or not item.api_key:
            raise ItemFileServiceError("Daemon is not configured for this item")


item_file_service = ItemFileService()
