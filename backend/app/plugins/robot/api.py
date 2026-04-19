import uuid

from fastapi import APIRouter, Header, HTTPException
from sqlmodel import col, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    Message,
    Robot,
    RobotCreate,
    RobotItem,
    RobotPublic,
    RobotsPublic,
    RobotUpdate,
)

from .api_support import (
    assert_bridge_permission,
    assert_item_permission,
    assert_robot_permission,
    clear_default_targets,
    current_robot_config,
    ensure_unique_binding_route_key,
    ensure_unique_robot_name,
    get_item_or_404,
    get_robot_or_404,
    normalize_binding_payload,
    normalize_robot_stack,
    serialize_binding,
    validate_binding_payload,
)
from .bridge_client import robot_bridge_client
from .contracts import RobotDispatchResponse, RobotInboundMessage
from .platforms import (
    RobotPlatformPublic,
    list_supported_robot_platforms,
    normalize_robot_config,
    normalize_robot_platform_id,
)
from .schemas import (
    RobotItemBindingCreate,
    RobotItemBindingPublic,
    RobotItemBindingUpdate,
)
from .service import robot_service

router = APIRouter(prefix="/robots", tags=["robots"])


@router.get("/platforms", response_model=list[RobotPlatformPublic])
def list_robot_platform_metadata() -> list[RobotPlatformPublic]:
    return list_supported_robot_platforms()


@router.get("/", response_model=RobotsPublic)
def read_robots(
    session: SessionDep,
    current_user: CurrentUser,
    skip: int = 0,
    limit: int = 100,
) -> RobotsPublic:
    if current_user.is_superuser:
        statement = (
            select(Robot)
            .order_by(col(Robot.created_at).desc())
            .offset(skip)
            .limit(limit)
        )
        robots = session.exec(statement).all()
    else:
        statement = (
            select(Robot)
            .where(Robot.owner_id == current_user.id)
            .order_by(col(Robot.created_at).desc())
            .offset(skip)
            .limit(limit)
        )
        robots = session.exec(statement).all()

    return RobotsPublic(data=robots, count=len(robots))


@router.get("/{id}", response_model=RobotPublic)
def read_robot(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
) -> RobotPublic:
    robot = get_robot_or_404(session, id)
    assert_robot_permission(robot, current_user)
    return robot


@router.post("/", response_model=RobotPublic)
def create_robot(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    robot_in: RobotCreate,
) -> RobotPublic:
    ensure_unique_robot_name(session, current_user, robot_in.name)

    payload = robot_in.model_dump()
    _, update = normalize_robot_stack(
        str(payload.get("platform") or ""),
        payload.get("config"),
    )

    robot = Robot.model_validate(
        robot_in,
        update={
            "owner_id": current_user.id,
            **update,
        },
    )
    session.add(robot)
    session.commit()
    session.refresh(robot)
    robot_bridge_client.notify_reload()
    return robot


@router.put("/{id}", response_model=RobotPublic)
def update_robot(
    *,
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    robot_in: RobotUpdate,
) -> RobotPublic:
    robot = get_robot_or_404(session, id)
    assert_robot_permission(robot, current_user)

    if robot_in.name and robot_in.name != robot.name:
        ensure_unique_robot_name(
            session,
            current_user,
            robot_in.name,
            exclude_robot_id=robot.id,
        )

    update_dict = robot_in.model_dump(exclude_unset=True)
    merged_platform = normalize_robot_platform_id(
        str(update_dict.get("platform") or robot.platform or robot.protocol or "")
    )
    if "config" in update_dict:
        merged_config = normalize_robot_config(
            merged_platform,
            update_dict.get("config"),
        )
    else:
        merged_config = current_robot_config(robot)
    _, normalized_update = normalize_robot_stack(merged_platform, merged_config)

    if "name" in update_dict and update_dict["name"] is not None:
        normalized_update["name"] = str(update_dict["name"]).strip()
    if "is_enabled" in update_dict:
        normalized_update["is_enabled"] = update_dict["is_enabled"]

    robot.sqlmodel_update(normalized_update)
    session.add(robot)
    session.commit()
    session.refresh(robot)
    robot_bridge_client.notify_reload()
    return robot


@router.delete("/{id}")
def delete_robot(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
) -> Message:
    robot = get_robot_or_404(session, id)
    assert_robot_permission(robot, current_user)

    session.delete(robot)
    session.commit()
    robot_bridge_client.notify_reload()
    return Message(message="Robot deleted successfully")


@router.get("/{id}/items", response_model=list[RobotItemBindingPublic])
def list_robot_item_bindings(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
) -> list[RobotItemBindingPublic]:
    robot = get_robot_or_404(session, id)
    assert_robot_permission(robot, current_user)

    bindings = session.exec(select(RobotItem).where(RobotItem.robot_id == id)).all()
    return [serialize_binding(session, binding) for binding in bindings]


@router.post("/{id}/items", response_model=RobotItemBindingPublic)
def bind_item_to_robot(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    body: RobotItemBindingCreate,
) -> RobotItemBindingPublic:
    robot = get_robot_or_404(session, id)
    assert_robot_permission(robot, current_user)

    item = get_item_or_404(session, body.item_id)
    assert_item_permission(item, current_user)

    existing = session.exec(
        select(RobotItem).where(
            RobotItem.robot_id == id,
            RobotItem.item_id == body.item_id,
        )
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Item is already bound to this robot")

    payload = normalize_binding_payload(body)
    validate_binding_payload(payload)
    route_key = ensure_unique_binding_route_key(
        session,
        id,
        item,
        chat_alias=payload.get("chat_alias"),
    )

    binding = RobotItem(
        robot_id=id,
        item_id=body.item_id,
        allow_chat=payload.get("allow_chat", True),
        receive_filtered_output=payload.get("receive_filtered_output", False),
        chat_alias=payload.get("chat_alias"),
        is_default_target=payload.get("is_default_target", False),
    )

    if binding.is_default_target:
        clear_default_targets(session, id)

    session.add(binding)
    session.commit()
    session.refresh(binding)

    response = serialize_binding(session, binding)
    response.route_key = route_key
    return response


@router.put("/{id}/items/{item_id}", response_model=RobotItemBindingPublic)
def update_robot_item_binding(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    item_id: uuid.UUID,
    body: RobotItemBindingUpdate,
) -> RobotItemBindingPublic:
    robot = get_robot_or_404(session, id)
    assert_robot_permission(robot, current_user)

    binding = session.exec(
        select(RobotItem).where(
            RobotItem.robot_id == id,
            RobotItem.item_id == item_id,
        )
    ).first()
    if not binding:
        raise HTTPException(status_code=404, detail="Robot item binding not found")

    item = get_item_or_404(session, item_id)
    assert_item_permission(item, current_user)

    payload = normalize_binding_payload(body)
    merged_payload = {
        "allow_chat": binding.allow_chat,
        "receive_filtered_output": binding.receive_filtered_output,
        "chat_alias": binding.chat_alias,
        "is_default_target": binding.is_default_target,
    }
    merged_payload.update(payload)
    validate_binding_payload(merged_payload)

    if "chat_alias" in payload:
        ensure_unique_binding_route_key(
            session,
            id,
            item,
            chat_alias=merged_payload.get("chat_alias"),
            exclude_item_id=item_id,
        )

    if merged_payload.get("is_default_target"):
        clear_default_targets(session, id, exclude_item_id=item_id)

    binding.allow_chat = merged_payload["allow_chat"]
    binding.receive_filtered_output = merged_payload["receive_filtered_output"]
    binding.chat_alias = merged_payload["chat_alias"]
    binding.is_default_target = merged_payload["is_default_target"]

    if not binding.allow_chat:
        binding.is_default_target = False

    session.add(binding)
    session.commit()
    session.refresh(binding)
    return serialize_binding(session, binding)


@router.delete("/{id}/items/{item_id}")
def unbind_item_from_robot(
    session: SessionDep,
    current_user: CurrentUser,
    id: uuid.UUID,
    item_id: uuid.UUID,
) -> Message:
    robot = get_robot_or_404(session, id)
    assert_robot_permission(robot, current_user)

    binding = session.exec(
        select(RobotItem).where(
            RobotItem.robot_id == id,
            RobotItem.item_id == item_id,
        )
    ).first()
    if not binding:
        raise HTTPException(status_code=404, detail="Robot item binding not found")

    session.delete(binding)
    session.commit()
    return Message(message="Robot item binding deleted successfully")


@router.post("/{id}/dispatch", response_model=RobotDispatchResponse)
async def dispatch_robot_message(
    session: SessionDep,
    id: uuid.UUID,
    body: RobotInboundMessage,
    x_termman_bridge_token: str | None = Header(default=None),
) -> RobotDispatchResponse:
    assert_bridge_permission(x_termman_bridge_token)
    robot = get_robot_or_404(session, id)
    return await robot_service.handle_inbound_message(session, robot, body)
