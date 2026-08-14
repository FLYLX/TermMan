from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass
from typing import Any

import httpx

from .config import settings
from .contracts import RobotDispatchResponse, RobotInboundMessage
from .platforms import BridgeRobot

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class _BridgeEvent:
    robot_id: str
    direction: str
    event: str
    status: str
    message: str | None
    payload: dict[str, Any]


_EVENT_QUEUE: queue.Queue[_BridgeEvent] = queue.Queue(
    maxsize=max(50, settings.ROBOT_BRIDGE_EVENT_QUEUE_SIZE)
)
_EVENT_WORKER_LOCK = threading.Lock()
_EVENT_WORKER_STARTED = False


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-TermPaws-Bridge-Token": settings.bridge_token,
    }


def load_runtime_config() -> tuple[
    list[BridgeRobot], dict[str, str], dict[str, str], dict[str, str]
]:
    response = httpx.get(
        f"{settings.ROBOT_BACKEND_URL.rstrip('/')}"
        f"{settings.API_V1_STR}/robots/bridge/runtime-config",
        headers=_headers(),
        timeout=10.0,
    )
    response.raise_for_status()
    data = response.json()
    robots = [
        BridgeRobot(
            id=str(item["id"]),
            platform=str(item["platform"]),
            protocol=str(item.get("protocol") or item["platform"]),
            provider=str(item.get("provider") or "nonebot2"),
            name=str(item.get("name") or item["id"]),
            runtime_config=dict(item["runtime_config"]),
            identity=str(item["identity"]),
        )
        for item in data.get("robots", [])
    ]
    return (
        robots,
        {
            str(key): str(value)
            for key, value in data.get("robot_id_by_identity", {}).items()
        },
        {
            str(key): str(value)
            for key, value in data.get("identity_by_robot_id", {}).items()
        },
        {str(key): str(value) for key, value in data.get("errors", {}).items()},
    )


async def dispatch_to_backend(
    robot_id: str,
    payload: RobotInboundMessage,
) -> RobotDispatchResponse:
    timeout = settings.ROBOT_BACKEND_DISPATCH_TIMEOUT_SECONDS
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                f"{settings.ROBOT_BACKEND_URL.rstrip('/')}"
                f"{settings.API_V1_STR}/robots/{robot_id}/dispatch",
                headers=_headers(),
                content=payload.model_dump_json(),
            )
            response.raise_for_status()
            return RobotDispatchResponse.model_validate(response.json())
    except httpx.TimeoutException as exc:
        raise TimeoutError(
            f"Backend dispatch timed out after {timeout:g}s"
        ) from exc


def _event_worker() -> None:
    with httpx.Client(timeout=1.5) as client:
        while True:
            event = _EVENT_QUEUE.get()
            try:
                client.post(
                    f"{settings.ROBOT_BACKEND_URL.rstrip('/')}"
                    f"{settings.API_V1_STR}/robots/{event.robot_id}/debug-events",
                    headers=_headers(),
                    json={
                        "direction": event.direction,
                        "event": event.event,
                        "status": event.status,
                        "message": event.message,
                        "payload": event.payload,
                    },
                )
            except Exception as exc:
                logger.debug(
                    "[RobotBridge] Dropped backend debug event robot=%s event=%s: %s",
                    event.robot_id,
                    event.event,
                    exc,
                )
            finally:
                _EVENT_QUEUE.task_done()


def _ensure_event_worker() -> None:
    global _EVENT_WORKER_STARTED

    if _EVENT_WORKER_STARTED:
        return
    with _EVENT_WORKER_LOCK:
        if _EVENT_WORKER_STARTED:
            return
        worker = threading.Thread(
            target=_event_worker,
            name="TermPaws-robot-debug-event-writer",
            daemon=True,
        )
        worker.start()
        _EVENT_WORKER_STARTED = True


def record_bridge_event(
    robot_id: str,
    *,
    direction: str,
    event: str,
    status: str = "ok",
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    _ensure_event_worker()
    try:
        _EVENT_QUEUE.put_nowait(
            _BridgeEvent(
                robot_id=str(robot_id),
                direction=direction,
                event=event,
                status=status,
                message=message,
                payload=payload or {},
            )
        )
    except queue.Full:
        logger.debug(
            "[RobotBridge] Debug event queue full; dropped robot=%s event=%s",
            robot_id,
            event,
        )


async def check_backend_health() -> dict[str, Any]:
    backend_status: dict[str, Any] = {"reachable": False}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(
                f"{settings.ROBOT_BACKEND_URL.rstrip('/')}"
                f"{settings.API_V1_STR}/utils/health-check/",
            )
            backend_status = {
                "reachable": resp.status_code == 200,
                "status_code": resp.status_code,
            }
    except Exception as exc:
        backend_status["error"] = str(exc)
    return backend_status
