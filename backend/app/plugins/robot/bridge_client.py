from __future__ import annotations

import logging
import uuid

import httpx

from app.core.config import settings

from .contracts import (
    RobotBridgeReloadResponse,
    RobotBridgeSendRequest,
    RobotReplyTarget,
)
from .debug_log import record_robot_event

logger = logging.getLogger(__name__)


class RobotBridgeClient:
    def __init__(self) -> None:
        self._base_url = settings.ROBOT_BRIDGE_URL.rstrip("/")
        self._shared_secret = settings.ROBOT_BRIDGE_SHARED_SECRET or settings.SECRET_KEY

    @property
    def base_url(self) -> str:
        return self._base_url

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-TermMan-Bridge-Token": self._shared_secret,
        }

    def _friendly_error(self, exc: Exception) -> str:
        message = str(exc)
        if "Name or service not known" in message or "[Errno -2]" in message:
            return (
                f"{self._base_url}: {message}. Backend cannot resolve this "
                "ROBOT_BRIDGE_URL. Set ROBOT_BRIDGE_URL in the root .env to "
                "the bridge address reachable from the backend runtime."
            )
        return f"{self._base_url}: {message}"

    def _request(
        self,
        method: str,
        path: str,
        *,
        timeout: float,
        **kwargs,
    ) -> httpx.Response:
        try:
            with httpx.Client(timeout=timeout) as client:
                response = client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers=self._headers(),
                    **kwargs,
                )
            response.raise_for_status()
            return response
        except Exception as exc:
            raise RuntimeError(self._friendly_error(exc)) from exc

    def get_health(self, timeout: float = 5.0) -> dict:
        response = self._request("GET", "/internal/health", timeout=timeout)
        data = response.json()
        if isinstance(data, dict):
            return data
        return {"data": data}

    def send_message(self, robot_id: uuid.UUID | str, target: RobotReplyTarget, text: str) -> None:
        if not text.strip():
            return

        robot_id_str = str(robot_id)
        payload = RobotBridgeSendRequest(
            robot_id=robot_id,
            target=target,
            text=text,
        )
        record_robot_event(
            robot_id_str,
            direction="backend_to_bridge",
            event="send_message",
            message=text,
            payload={
                "target_type": target.target_type,
                "target_id": target.target_id,
            },
        )
        try:
            self._request(
                "POST",
                "/internal/send",
                timeout=10.0,
                content=payload.model_dump_json(),
            )
        except Exception as exc:
            record_robot_event(
                robot_id_str,
                direction="backend_to_bridge",
                event="send_message",
                status="error",
                message=str(exc),
            )
            raise

    def notify_reload(self) -> tuple[bool, str]:
        if not settings.ROBOT_BRIDGE_AUTO_RELOAD:
            return False, "Bridge auto reload is disabled"

        try:
            response = self._request("POST", "/internal/reload", timeout=5.0)
            result = RobotBridgeReloadResponse.model_validate(response.json())
            return result.success, result.detail
        except Exception as exc:
            logger.info("[RobotBridge] reload notification skipped: %s", exc)
            return False, str(exc)


robot_bridge_client = RobotBridgeClient()
