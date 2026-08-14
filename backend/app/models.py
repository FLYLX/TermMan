import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List

from pydantic import EmailStr
from sqlalchemy import DateTime, JSON, String, Enum as SAEnum
from sqlmodel import Field, Relationship, SQLModel
from sqlalchemy.dialects.sqlite import CHAR
from sqlalchemy import TypeDecorator

# Add UUID support for SQLite
class SQLiteUUID(TypeDecorator):
    impl = CHAR
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return value
        return str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return value
        return uuid.UUID(value)


def get_datetime_utc() -> datetime:
    return datetime.now(timezone.utc)


# Enums
class ItemStatus(str, Enum):
    stopped = "stopped"
    running = "running"
    starting = "starting"
    stopping = "stopping"
    error = "error"


# Shared properties
class UserBase(SQLModel):
    email: EmailStr = Field(unique=True, index=True, max_length=255)
    is_active: bool = True
    is_superuser: bool = False
    full_name: Optional[str] = Field(default=None, max_length=255)


# Properties to receive via API on creation
class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)


class UserRegister(SQLModel):
    email: EmailStr = Field(max_length=255)
    password: str = Field(min_length=8, max_length=128)
    full_name: Optional[str] = Field(default=None, max_length=255)


# Properties to receive via API on update, all are optional
class UserUpdate(UserBase):
    email: Optional[EmailStr] = Field(default=None, max_length=255)  # type: ignore
    password: Optional[str] = Field(default=None, min_length=8, max_length=128)


class UserUpdateMe(SQLModel):
    full_name: Optional[str] = Field(default=None, max_length=255)
    email: Optional[EmailStr] = Field(default=None, max_length=255)


class UpdatePassword(SQLModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


# Database model, database table inferred from class name
# Link models (many-to-many relationships) - defined early for reference
class ItemHandlerItem(SQLModel, table=True):
    item_handler_id: uuid.UUID = Field(
        foreign_key="itemhandler.id", primary_key=True, ondelete="CASCADE", sa_type=SQLiteUUID, index=True
    )
    item_id: uuid.UUID = Field(
        foreign_key="item.id", primary_key=True, ondelete="CASCADE", sa_type=SQLiteUUID, index=True
    )


class ItemHandlerUser(SQLModel, table=True):
    item_handler_id: uuid.UUID = Field(
        foreign_key="itemhandler.id", primary_key=True, ondelete="CASCADE", sa_type=SQLiteUUID, index=True
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id", primary_key=True, ondelete="CASCADE", sa_type=SQLiteUUID, index=True
    )


class RobotItem(SQLModel, table=True):
    robot_id: uuid.UUID = Field(
        foreign_key="robot.id", primary_key=True, ondelete="CASCADE", sa_type=SQLiteUUID, index=True
    )
    item_id: uuid.UUID = Field(
        foreign_key="item.id", primary_key=True, ondelete="CASCADE", sa_type=SQLiteUUID, index=True
    )
    allow_chat: bool = Field(default=True)
    receive_filtered_output: bool = Field(default=False)
    chat_alias: Optional[str] = Field(default=None, max_length=64)
    is_default_target: bool = Field(default=False)


class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True, sa_type=SQLiteUUID)
    hashed_password: str
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True)
    )
    items: List["Item"] = Relationship(back_populates="owner", cascade_delete=True)
    handlers: List["ItemHandler"] = Relationship(back_populates="users", link_model=ItemHandlerUser)
    owned_handlers: List["ItemHandler"] = Relationship(back_populates="owner", cascade_delete=True)
    robots: List["Robot"] = Relationship(back_populates="owner", cascade_delete=True)


# Properties to return via API, id is always required
class UserPublic(UserBase):
    id: uuid.UUID
    created_at: Optional[datetime] = None


class UsersPublic(SQLModel):
    data: list[UserPublic]
    count: int


# Shared properties
class ItemBase(SQLModel):
    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = Field(default=None, max_length=255)
    status: ItemStatus = Field(default=ItemStatus.stopped, sa_type=SAEnum(ItemStatus))
    log_max_size_mb: Optional[int] = Field(default=100, ge=10, le=1000)
    socket_host: Optional[str] = Field(default="localhost", max_length=255)
    socket_port: Optional[int] = Field(default=9000, ge=1, le=65535)
    socket_connected: Optional[bool] = Field(default=False)
    socket_last_connected: Optional[datetime] = Field(default=None, sa_type=DateTime(timezone=True))
    api_key: Optional[str] = Field(default=None, max_length=255)
    command: Optional[str] = Field(default=None, max_length=500)
    working_directory: Optional[str] = Field(default=None, max_length=255)
    
    input_filter_enabled: bool = Field(default=False)
    input_filter_rules: dict = Field(default_factory=dict, sa_type=JSON)
    
    output_filter_enabled: bool = Field(default=False)
    output_filter_rules: dict = Field(default_factory=dict, sa_type=JSON)


# Properties to receive on item creation
class ItemCreate(ItemBase):
    pass


# Properties to receive on item update
class ItemUpdate(ItemBase):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)  # type: ignore
    description: Optional[str] = Field(default=None, max_length=255)
    status: Optional[ItemStatus] = Field(default=None, sa_type=SAEnum(ItemStatus))
    log_max_size_mb: Optional[int] = Field(default=None, ge=10, le=1000)
    socket_host: Optional[str] = Field(default=None, max_length=255)
    socket_port: Optional[int] = Field(default=None, ge=1, le=65535)
    socket_connected: Optional[bool] = None
    socket_last_connected: Optional[datetime] = None
    command: Optional[str] = Field(default=None, max_length=500)
    working_directory: Optional[str] = Field(default=None, max_length=255)
    
    input_filter_enabled: Optional[bool] = None
    input_filter_rules: Optional[dict] = Field(default=None, sa_type=JSON)
    
    output_filter_enabled: Optional[bool] = None
    output_filter_rules: Optional[dict] = Field(default=None, sa_type=JSON)


# Database model, database table inferred from class name
class Item(ItemBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True, sa_type=SQLiteUUID)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True)
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"onupdate": get_datetime_utc}
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", sa_type=SQLiteUUID, index=True
    )
    owner: Optional[User] = Relationship(back_populates="items")
    handlers: List["ItemHandler"] = Relationship(back_populates="items", link_model=ItemHandlerItem)
    robots: List["Robot"] = Relationship(back_populates="items", link_model=RobotItem)


# Properties to return via API, id is always required
class ItemPublic(ItemBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ITEM_HANDLER models
class ItemHandlerBase(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    model: Optional[str] = Field(default=None, max_length=255)
    api_key: Optional[str] = Field(default=None, max_length=255)
    api_url: Optional[str] = Field(default=None, max_length=255)
    model_parameters: dict = Field(default_factory=dict, sa_type=JSON)
    enabled_skills: Optional[List[str]] = Field(default=None, sa_type=JSON)
    enabled_mcp_servers: Optional[List[str]] = Field(default=None, sa_type=JSON)
    enabled_knowledge_files: Optional[List[str]] = Field(default=None, sa_type=JSON)


class ItemHandlerCreate(ItemHandlerBase):
    pass


class ItemHandlerUpdate(ItemHandlerBase):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    model: Optional[str] = Field(default=None, max_length=255)
    api_key: Optional[str] = Field(default=None, max_length=255)
    api_url: Optional[str] = Field(default=None, max_length=255)
    model_parameters: Optional[dict] = Field(default=None, sa_type=JSON)
    enabled_skills: Optional[List[str]] = Field(default=None, sa_type=JSON)
    enabled_mcp_servers: Optional[List[str]] = Field(default=None, sa_type=JSON)
    enabled_knowledge_files: Optional[List[str]] = Field(default=None, sa_type=JSON)
    clear_api_key: bool = False


class ItemHandler(ItemHandlerBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True, sa_type=SQLiteUUID)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True)
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"onupdate": get_datetime_utc}
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", sa_type=SQLiteUUID, index=True
    )
    items: List[Item] = Relationship(back_populates="handlers", link_model=ItemHandlerItem)
    users: List[User] = Relationship(back_populates="handlers", link_model=ItemHandlerUser)
    owner: Optional[User] = Relationship(back_populates="owned_handlers")


class ItemHandlerPublic(SQLModel):
    name: str
    model: Optional[str] = None
    api_url: Optional[str] = None
    model_parameters: dict = Field(default_factory=dict)
    enabled_skills: Optional[List[str]] = None
    enabled_mcp_servers: Optional[List[str]] = None
    enabled_knowledge_files: Optional[List[str]] = None
    has_api_key: bool = False
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RobotBase(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    platform: str = Field(default="qq_official", max_length=50)
    protocol: str = Field(default="qq_official", max_length=50)
    provider: str = Field(default="nonebot2", max_length=50)
    app_id: Optional[str] = Field(default=None, max_length=64)
    app_secret: Optional[str] = Field(default=None, max_length=255)
    bot_token: Optional[str] = Field(default=None, max_length=255)
    use_websocket: bool = True
    is_enabled: bool = True
    config: dict = Field(default_factory=dict, sa_type=JSON)


class RobotCreate(RobotBase):
    pass


class RobotUpdate(SQLModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    platform: Optional[str] = Field(default=None, max_length=50)
    protocol: Optional[str] = Field(default=None, max_length=50)
    provider: Optional[str] = Field(default=None, max_length=50)
    app_id: Optional[str] = Field(default=None, max_length=64)
    app_secret: Optional[str] = Field(default=None, max_length=255)
    bot_token: Optional[str] = Field(default=None, max_length=255)
    use_websocket: Optional[bool] = None
    is_enabled: Optional[bool] = None
    config: Optional[dict] = Field(default=None, sa_type=JSON)


class Robot(RobotBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True, sa_type=SQLiteUUID)
    created_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True)
    )
    updated_at: datetime = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),
        sa_column_kwargs={"onupdate": get_datetime_utc}
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", sa_type=SQLiteUUID, index=True
    )
    owner: Optional[User] = Relationship(back_populates="robots")
    items: List[Item] = Relationship(back_populates="robots", link_model=RobotItem)


class RobotPublic(RobotBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RobotsPublic(SQLModel):
    data: list[RobotPublic]
    count: int


class ItemChatSessionBase(SQLModel):
    messages: List[dict] = Field(default_factory=list, sa_type=JSON)


class ItemChatSession(ItemChatSessionBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True, sa_type=SQLiteUUID)
    item_id: uuid.UUID = Field(foreign_key="item.id", nullable=False, ondelete="CASCADE", sa_type=SQLiteUUID, index=True)
    created_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True))
    updated_at: datetime = Field(default_factory=get_datetime_utc, sa_type=DateTime(timezone=True), sa_column_kwargs={"onupdate": get_datetime_utc})


class ItemChatSessionPublic(ItemChatSessionBase):
    id: uuid.UUID
    item_id: uuid.UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ItemsPublic(SQLModel):
    data: List[ItemPublic]
    count: int


# Generic message
class Message(SQLModel):
    message: str


# JSON payload containing access token
class Token(SQLModel):
    access_token: str
    token_type: str = "bearer"


# Contents of JWT token
class TokenPayload(SQLModel):
    sub: Optional[str] = None


class NewPassword(SQLModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)
