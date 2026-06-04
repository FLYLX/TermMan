from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings


def is_robot_plugin_enabled() -> bool:
    return bool(settings.ROBOT_PLUGIN_ENABLED)


def include_robot_plugin_router(api_router: APIRouter) -> None:
    if not is_robot_plugin_enabled():
        return

    from .api import router

    api_router.include_router(router)


def __getattr__(name: str):
    if name == "RobotService":
        from .service import RobotService

        return RobotService
    if name == "robot_service":
        from .service import robot_service

        return robot_service
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    "RobotService",
    "include_robot_plugin_router",
    "is_robot_plugin_enabled",
    "robot_service",
]
