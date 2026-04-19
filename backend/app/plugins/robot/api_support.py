from __future__ import annotations

import uuid
from typing import Any

from fastapi import HTTPException
from sqlmodel import Session, select

from app.core.config import settings
from app.models import Item, Robot, RobotItem, User

from .platforms import (
    extract_robot_credentials,
    normalize_robot_platform_id,
    validate_robot_platform_config,
)
from .schemas import (
    RobotItemBindingCreate,
    RobotItemBindingPublic,
    RobotItemBindingUpdate,
)
from .service import robot_service


def get_robot_or_404(session: Session, robot_id: uuid.UUID) -> Robot:
    robot = session.get(Robot, robot_id)
    if not robot:
        raise HTTPException(status_code=404, detail="Robot not found")
    return robot


def get_item_or_404(session: Session, item_id: uuid.UUID) -> Item:
    item = session.get(Item, item_id)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    return item


def assert_robot_permission(robot: Robot, current_user: User) -> None:
    if not current_user.is_superuser and robot.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")


def assert_item_permission(item: Item, current_user: User) -> None:
    if not current_user.is_superuser and item.owner_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not enough permissions")


def ensure_unique_robot_name(
    session: Session,
    current_user: User,
    name: str,
    *,
    exclude_robot_id: uuid.UUID | None = None,
) -> None:
    statement = select(Robot).where(
        Robot.owner_id == current_user.id,
        Robot.name == name,
    )
    if exclude_robot_id is not None:
        statement = statement.where(Robot.id != exclude_robot_id)

    existing = session.exec(statement).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail="A robot with this name already exists for your account.",
        )


def normalize_binding_payload(
    body: RobotItemBindingCreate | RobotItemBindingUpdate,
) -> dict[str, Any]:
    payload = body.model_dump(exclude_unset=True)
    if "chat_alias" in payload:
        payload["chat_alias"] = robot_service.normalize_chat_alias(payload.get("chat_alias"))
    return payload


def validate_binding_payload(payload: dict[str, Any]) -> None:
    allow_chat = payload.get("allow_chat")
    is_default_target = payload.get("is_default_target")
    if allow_chat is False and is_default_target:
        raise HTTPException(
            status_code=400,
            detail="Default target must also allow chat.",
        )


def ensure_unique_binding_route_key(
    session: Session,
    robot_id: uuid.UUID,
    item: Item,
    *,
    chat_alias: str | None,
    exclude_item_id: uuid.UUID | None = None,
) -> str:
    temp_binding = RobotItem(
        robot_id=robot_id,
        item_id=item.id,
        chat_alias=chat_alias,
    )
    route_key = robot_service.build_route_key(item, temp_binding)
    existing_route_keys = robot_service.collect_route_keys(
        session,
        robot_id,
        exclude_item_id=exclude_item_id,
    )
    if route_key in existing_route_keys:
        raise HTTPException(
            status_code=400,
            detail=f"Binding route key `{route_key}` is already in use.",
        )
    return route_key


def clear_default_targets(
    session: Session,
    robot_id: uuid.UUID,
    *,
    exclude_item_id: uuid.UUID | None = None,
) -> None:
    bindings = session.exec(select(RobotItem).where(RobotItem.robot_id == robot_id)).all()
    for binding in bindings:
        if exclude_item_id and binding.item_id == exclude_item_id:
            continue
        binding.is_default_target = False
        session.add(binding)


def serialize_binding(
    session: Session,
    binding: RobotItem,
) -> RobotItemBindingPublic:
    item = get_item_or_404(session, binding.item_id)
    route_key = robot_service.build_route_key(item, binding)
    return RobotItemBindingPublic(
        robot_id=binding.robot_id,
        item_id=binding.item_id,
        item_title=item.title,
        allow_chat=binding.allow_chat,
        receive_filtered_output=binding.receive_filtered_output,
        chat_alias=binding.chat_alias,
        route_key=route_key,
        is_default_target=binding.is_default_target,
    )


def assert_bridge_permission(header_value: str | None) -> None:
    expected = settings.ROBOT_BRIDGE_SHARED_SECRET or settings.SECRET_KEY
    if not expected or header_value != expected:
        raise HTTPException(status_code=403, detail="Invalid robot bridge token")


def normalize_robot_stack(
    platform_id: str,
    config: dict[str, Any] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    normalized_platform = normalize_robot_platform_id(platform_id)
    try:
        normalized_config = validate_robot_platform_config(normalized_platform, config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    credentials = normalized_config["credentials"]
    update: dict[str, Any] = {
        "platform": normalized_platform,
        "protocol": normalized_platform,
        "provider": "nonebot2",
        "config": normalized_config,
    }

    if normalized_platform == "qq_official":
        update["app_id"] = credentials.get("app_id")
        update["app_secret"] = credentials.get("app_secret")
        update["bot_token"] = credentials.get("bot_token")
        update["use_websocket"] = bool(
            normalized_config["options"].get("use_websocket", True)
        )
    else:
        update["app_id"] = None
        update["app_secret"] = None
        update["bot_token"] = None

    return normalized_config, update


def current_robot_config(robot: Robot) -> dict[str, Any]:
    platform_id = normalize_robot_platform_id(robot.platform or robot.protocol)
    return {
        "credentials": extract_robot_credentials(robot),
        "options": validate_robot_platform_config(platform_id, robot.config)["options"],
    }
