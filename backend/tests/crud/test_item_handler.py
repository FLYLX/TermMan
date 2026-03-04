from fastapi.encoders import jsonable_encoder
from sqlmodel import Session

from app import crud
from app.models import ItemHandler, ItemHandlerCreate, ItemHandlerUpdate
from tests.utils.item_handler import create_random_item_handler
from tests.utils.user import create_random_user
from tests.utils.utils import random_lower_string


def test_create_item_handler(db: Session) -> None:
    user = create_random_user(db)
    assert user.id is not None
    name = random_lower_string()
    model = random_lower_string()
    api_key = random_lower_string()
    api_url = random_lower_string()
    
    item_handler_in = ItemHandlerCreate(
        name=name,
        model=model,
        api_key=api_key,
        api_url=api_url
    )
    
    item_handler = crud.create_item_handler(session=db, item_handler_in=item_handler_in, owner_id=user.id)
    
    assert item_handler.name == name
    assert item_handler.model == model
    assert item_handler.api_key == api_key
    assert item_handler.api_url == api_url
    assert item_handler.owner_id == user.id
    assert hasattr(item_handler, "id")


def test_get_item_handler(db: Session) -> None:
    # 创建一个随机的ItemHandler
    item_handler_1 = create_random_item_handler(db)
    
    # 通过ID获取ItemHandler
    item_handler_2 = crud.get_item_handler(session=db, item_handler_id=item_handler_1.id)
    
    assert item_handler_2 is not None
    assert item_handler_1.id == item_handler_2.id
    assert item_handler_1.name == item_handler_2.name
    assert jsonable_encoder(item_handler_1) == jsonable_encoder(item_handler_2)


def test_get_item_handler_by_name(db: Session) -> None:
    # 创建一个随机的用户
    user = create_random_user(db)
    assert user.id is not None
    
    # 创建一个特定名称的ItemHandler
    name = random_lower_string()
    item_handler_in = ItemHandlerCreate(name=name)
    item_handler_1 = crud.create_item_handler(session=db, item_handler_in=item_handler_in, owner_id=user.id)
    
    # 通过名称和所有者ID获取ItemHandler
    item_handler_2 = crud.get_item_handler_by_name(session=db, name=name, owner_id=user.id)
    
    assert item_handler_2 is not None
    assert item_handler_1.id == item_handler_2.id


def test_update_item_handler(db: Session) -> None:
    # 创建一个随机的ItemHandler
    item_handler_1 = create_random_item_handler(db)
    
    # 更新ItemHandler的属性
    new_name = random_lower_string()
    new_model = random_lower_string()
    item_handler_update = ItemHandlerUpdate(name=new_name, model=new_model)
    
    # 执行更新操作
    item_handler_2 = crud.update_item_handler(
        session=db, 
        db_item_handler=item_handler_1, 
        item_handler_in=item_handler_update
    )
    
    # 验证更新是否成功
    assert item_handler_2.name == new_name
    assert item_handler_2.model == new_model
    assert item_handler_2.id == item_handler_1.id  # ID应该保持不变


def test_delete_item_handler(db: Session) -> None:
    # 创建一个随机的ItemHandler
    item_handler = create_random_item_handler(db)
    item_handler_id = item_handler.id
    
    # 删除ItemHandler
    crud.delete_item_handler(session=db, item_handler_id=item_handler_id)
    
    # 验证ItemHandler是否被删除
    item_handler_2 = crud.get_item_handler(session=db, item_handler_id=item_handler_id)
    assert item_handler_2 is None


def test_get_item_handlers(db: Session) -> None:
    # 创建一个随机的用户
    user = create_random_user(db)
    assert user.id is not None
    
    # 创建多个ItemHandler
    item_handlers_count = 3
    for _ in range(item_handlers_count):
        name = random_lower_string()
        item_handler_in = ItemHandlerCreate(name=name)
        crud.create_item_handler(session=db, item_handler_in=item_handler_in, owner_id=user.id)
    
    # 获取该用户的所有ItemHandler
    item_handlers = crud.get_item_handlers(session=db, owner_id=user.id)
    
    # 验证数量是否正确
    assert len(item_handlers) >= item_handlers_count