from __future__ import annotations

from typing import Any

import httpx

from .config import settings
from .contracts import RobotDispatchResponse, RobotInboundMessage
from .platforms import BridgeRobot


def _headers() -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "X-TermMan-Bridge-Token": settings.bridge_token,
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
            route_key=str(item["route_key"]) if item.get("route_key") else None,
            public_reverse_ws_url=str(item["public_reverse_ws_url"])
            if item.get("public_reverse_ws_url")
            else None,
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
    async with httpx.AsyncClient(timeout=30.0) as client:
        response = await client.post(
            f"{settings.ROBOT_BACKEND_URL.rstrip('/')}"
            f"{settings.API_V1_STR}/robots/{robot_id}/dispatch",
            headers=_headers(),
            content=payload.model_dump_json(),
        )
        response.raise_for_status()
        return RobotDispatchResponse.model_validate(response.json())


def record_bridge_event(
    robot_id: str,
    *,
    direction: str,
    event: str,
    status: str = "ok",
    message: str | None = None,
    payload: dict[str, Any] | None = None,
) -> None:
    try:
        with httpx.Client(timeout=1.5) as client:
            client.post(
                f"{settings.ROBOT_BACKEND_URL.rstrip('/')}"
                f"{settings.API_V1_STR}/robots/{robot_id}/debug-events",
                headers=_headers(),
                json={
                    "direction": direction,
                    "event": event,
                    "status": status,
                    "message": message,
                    "payload": payload or {},
                },
            )
    except Exception:
        pass


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
