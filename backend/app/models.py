import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, List

from pydantic import EmailStr
from sqlalchemy import DateTime, JSON, String
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


class ItemType(str, Enum):
    normal = "normal"
    parent = "parent"
    child = "child"


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
        foreign_key="itemhandler.id", primary_key=True, ondelete="CASCADE", sa_type=SQLiteUUID
    )
    item_id: uuid.UUID = Field(
        foreign_key="item.id", primary_key=True, ondelete="CASCADE", sa_type=SQLiteUUID
    )


class ItemHandlerUser(SQLModel, table=True):
    item_handler_id: uuid.UUID = Field(
        foreign_key="itemhandler.id", primary_key=True, ondelete="CASCADE", sa_type=SQLiteUUID
    )
    user_id: uuid.UUID = Field(
        foreign_key="user.id", primary_key=True, ondelete="CASCADE", sa_type=SQLiteUUID
    )


class User(UserBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True, sa_type=SQLiteUUID)
    hashed_password: str
    created_at: Optional[datetime] = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    items: List["Item"] = Relationship(back_populates="owner", cascade_delete=True)
    handlers: List["ItemHandler"] = Relationship(back_populates="users", link_model=ItemHandlerUser)
    item_handlers: List["ItemHandler"] = Relationship(back_populates="owner", cascade_delete=True)


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
    status: ItemStatus = Field(default=ItemStatus.stopped, sa_type=String(32))
    type: ItemType = Field(default=ItemType.normal, sa_type=String(32))
    config: Optional[dict] = Field(default=None, sa_type=JSON)
    resource_usage: Optional[dict] = Field(default=None, sa_type=JSON)
    log_path: Optional[str] = Field(default=None, max_length=255)


# Properties to receive on item creation
class ItemCreate(ItemBase):
    pass


# Properties to receive on item update
class ItemUpdate(ItemBase):
    title: Optional[str] = Field(default=None, min_length=1, max_length=255)  # type: ignore
    status: Optional[ItemStatus] = None
    type: Optional[ItemType] = None


# Database model, database table inferred from class name
class Item(ItemBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True, sa_type=SQLiteUUID)
    created_at: Optional[datetime] = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: Optional[datetime] = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
        sa_column_kwargs={"onupdate": get_datetime_utc}
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", sa_type=SQLiteUUID
    )
    owner: Optional[User] = Relationship(back_populates="items")
    handlers: List["ItemHandler"] = Relationship(back_populates="items", link_model=ItemHandlerItem)


# Properties to return via API, id is always required
class ItemPublic(ItemBase):
    id: uuid.UUID
    owner_id: uuid.UUID
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ITEM_HANDLER models
class ItemHandlerBase(SQLModel):
    name: str = Field(min_length=1, max_length=255)
    model: str = Field(min_length=1, max_length=255)
    api_key: Optional[str] = Field(default=None, max_length=255)
    api_url: Optional[str] = Field(default=None, max_length=255)


class ItemHandlerCreate(ItemHandlerBase):
    pass


class ItemHandlerUpdate(ItemHandlerBase):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    model: Optional[str] = Field(default=None, min_length=1, max_length=255)


class ItemHandler(ItemHandlerBase, table=True):
    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True, sa_type=SQLiteUUID)
    created_at: Optional[datetime] = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
    )
    updated_at: Optional[datetime] = Field(
        default_factory=get_datetime_utc,
        sa_type=DateTime(timezone=True),  # type: ignore
        sa_column_kwargs={"onupdate": get_datetime_utc}
    )
    owner_id: uuid.UUID = Field(
        foreign_key="user.id", nullable=False, ondelete="CASCADE", sa_type=SQLiteUUID
    )
    items: List[Item] = Relationship(back_populates="handlers", link_model=ItemHandlerItem)
    users: List[User] = Relationship(back_populates="handlers", link_model=ItemHandlerUser)
    owner: Optional[User] = Relationship(back_populates="item_handlers")


class ItemHandlerPublic(ItemHandlerBase):
    id: uuid.UUID
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