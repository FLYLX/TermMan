from sqlmodel import Session

from app.models import Robot, RobotCreate
from tests.utils.user import create_random_user
from tests.utils.utils import random_lower_string


def create_random_robot(db: Session) -> Robot:
    user = create_random_user(db)
    owner_id = user.id
    assert owner_id is not None

    robot_in = RobotCreate(
        name=f"robot-{random_lower_string()}",
        platform="qq_official",
        protocol="qq_official",
        provider="nonebot2",
        use_websocket=True,
        config={
            "credentials": {
                "app_id": f"app-{random_lower_string()}",
                "app_secret": random_lower_string(),
                "bot_token": random_lower_string(),
            },
            "options": {},
        },
    )
    robot = Robot.model_validate(
        robot_in,
        update={
            "owner_id": owner_id,
            "app_id": robot_in.config["credentials"]["app_id"],
            "app_secret": robot_in.config["credentials"]["app_secret"],
            "bot_token": robot_in.config["credentials"]["bot_token"],
        },
    )
    db.add(robot)
    db.commit()
    db.refresh(robot)
    return robot
