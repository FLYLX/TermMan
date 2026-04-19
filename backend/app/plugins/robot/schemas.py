from __future__ import annotations

import uuid

from pydantic import BaseModel


class RobotItemBindingCreate(BaseModel):
    item_id: uuid.UUID
    allow_chat: bool = True
    receive_filtered_output: bool = False
    chat_alias: str | None = None
    is_default_target: bool = False


class RobotItemBindingUpdate(BaseModel):
    allow_chat: bool | None = None
    receive_filtered_output: bool | None = None
    chat_alias: str | None = None
    is_default_target: bool | None = None


class RobotItemBindingPublic(BaseModel):
    robot_id: uuid.UUID
    item_id: uuid.UUID
    item_title: str
    allow_chat: bool
    receive_filtered_output: bool
    chat_alias: str | None = None
    route_key: str
    is_default_target: bool
