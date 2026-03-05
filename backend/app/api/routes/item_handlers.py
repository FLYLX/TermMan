import uuid
from typing import Any, List

from fastapi import APIRouter, HTTPException
from sqlmodel import col, func, select

from app.api.deps import CurrentUser, SessionDep
from app.models import (
    ItemHandler, 
    ItemHandlerCreate, 
    ItemHandlerPublic, 
    ItemHandlerUpdate, 
    Message
)

router = APIRouter(prefix="/item-handlers", tags=["item-handlers"])


@router.get("/", response_model=List[ItemHandlerPublic])
def read_item_handlers(
    session: SessionDep, current_user: CurrentUser, skip: int = 0, limit: int = 100
) -> Any:
    """
    Retrieve item handlers.
    """
    
    if current_user.is_superuser:
        # 超级用户可以查看所有item handlers
        statement = (
            select(ItemHandler)
            .order_by(col(ItemHandler.created_at).desc())
            .offset(skip)
            .limit(limit)
        )
    else:
        # 普通用户只能查看自己的item handlers
        statement = (
            select(ItemHandler)
            .where(ItemHandler.owner_id == current_user.id)
            .order_by(col(ItemHandler.created_at).desc())
            .offset(skip)
            .limit(limit)
        )
    
    item_handlers = session.exec(statement).all()
    return item_handlers


@router.get("/{id}", response_model=ItemHandlerPublic)
def read_item_handler(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Any:
    """
    Get item handler by ID.
    """
    item_handler = session.get(ItemHandler, id)
    if not item_handler:
        raise HTTPException(status_code=404, detail="Item handler not found")
    
    # 检查权限：超级用户或所有者可以查看
    if not current_user.is_superuser and (item_handler.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    return item_handler


@router.post("/", response_model=ItemHandlerPublic)
def create_item_handler(
    *, session: SessionDep, current_user: CurrentUser, item_handler_in: ItemHandlerCreate
) -> Any:
    """
    Create new item handler.
    """
    
    # 检查名称是否已存在
    existing_item_handler = session.exec(
        select(ItemHandler).where(
            ItemHandler.name == item_handler_in.name,
            ItemHandler.owner_id == current_user.id
        )
    ).first()
    
    if existing_item_handler:
        raise HTTPException(
            status_code=400,
            detail="An item handler with this name already exists for your account.",
        )
    
    # 创建新的item handler
    item_handler = ItemHandler.model_validate(
        item_handler_in, update={"owner_id": current_user.id}
    )
    
    session.add(item_handler)
    session.commit()
    session.refresh(item_handler)
    
    return item_handler


@router.put("/{id}", response_model=ItemHandlerPublic)
def update_item_handler(
    *, 
    session: SessionDep, 
    current_user: CurrentUser, 
    id: uuid.UUID, 
    item_handler_in: ItemHandlerUpdate
) -> Any:
    """
    Update an item handler.
    """
    item_handler = session.get(ItemHandler, id)
    if not item_handler:
        raise HTTPException(status_code=404, detail="Item handler not found")
    
    # 检查权限：超级用户或所有者可以更新
    if not current_user.is_superuser and (item_handler.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    # 如果更新了名称，检查新名称是否已存在
    if item_handler_in.name and item_handler_in.name != item_handler.name:
        existing_item_handler = session.exec(
            select(ItemHandler).where(
                ItemHandler.name == item_handler_in.name,
                ItemHandler.owner_id == current_user.id,
                ItemHandler.id != id  # 排除当前item handler
            )
        ).first()
        
        if existing_item_handler:
            raise HTTPException(
                status_code=400,
                detail="An item handler with this name already exists for your account.",
            )
    
    # 更新item handler
    update_dict = item_handler_in.model_dump(exclude_unset=True)
    item_handler.sqlmodel_update(update_dict)
    
    session.add(item_handler)
    session.commit()
    session.refresh(item_handler)
    
    return item_handler


@router.delete("/{id}")
def delete_item_handler(
    session: SessionDep, current_user: CurrentUser, id: uuid.UUID
) -> Message:
    """
    Delete an item handler.
    """
    item_handler = session.get(ItemHandler, id)
    if not item_handler:
        raise HTTPException(status_code=404, detail="Item handler not found")
    
    # 检查权限：超级用户或所有者可以删除
    if not current_user.is_superuser and (item_handler.owner_id != current_user.id):
        raise HTTPException(status_code=403, detail="Not enough permissions")
    
    session.delete(item_handler)
    session.commit()
    
    return Message(message="Item handler deleted successfully")
