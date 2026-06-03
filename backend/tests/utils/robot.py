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
        platform="onebot_v11",
        protocol="onebot_v11",
        provider="nonebot2",
        use_websocket=False,
        config={
            "credentials": {
                "self_id": random_lower_string(),
                "ws_url": "ws://napcat.test:3001",
            },
            "options": {},
        },
    )
    robot = Robot.model_validate(
        robot_in,
        update={
            "owner_id": owner_id,
        },
    )
    db.add(robot)
    db.commit()
    db.refresh(robot)
    return robot
