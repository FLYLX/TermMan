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

    def _headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-TermMan-Bridge-Token": self._shared_secret,
        }

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
            with httpx.Client(timeout=10.0) as client:
                response = client.post(
                    f"{self._base_url}/internal/send",
                    headers=self._headers(),
                    content=payload.model_dump_json(),
                )
                response.raise_for_status()
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
            with httpx.Client(timeout=5.0) as client:
                response = client.post(
                    f"{self._base_url}/internal/reload",
                    headers=self._headers(),
                )
                response.raise_for_status()
                result = RobotBridgeReloadResponse.model_validate(response.json())
                return result.success, result.detail
        except Exception as exc:
            logger.info("[RobotBridge] reload notification skipped: %s", exc)
            return False, str(exc)


robot_bridge_client = RobotBridgeClient()
