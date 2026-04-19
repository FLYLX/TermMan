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

        payload = RobotBridgeSendRequest(
            robot_id=robot_id,
            target=target,
            text=text,
        )
        with httpx.Client(timeout=10.0) as client:
            response = client.post(
                f"{self._base_url}/internal/send",
                headers=self._headers(),
                content=payload.model_dump_json(),
            )
            response.raise_for_status()

    def notify_reload(self) -> None:
        if not settings.ROBOT_BRIDGE_AUTO_RELOAD:
            return

        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.post(
                    f"{self._base_url}/internal/reload",
                    headers=self._headers(),
                )
                response.raise_for_status()
                RobotBridgeReloadResponse.model_validate(response.json())
        except Exception as exc:
            logger.info("[RobotBridge] reload notification skipped: %s", exc)


robot_bridge_client = RobotBridgeClient()
