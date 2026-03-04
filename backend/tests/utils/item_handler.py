from sqlmodel import Session

from app import crud
from app.models import ItemHandler, ItemHandlerCreate
from tests.utils.user import create_random_user
from tests.utils.utils import random_lower_string


def create_random_item_handler(db: Session) -> ItemHandler:
    user = create_random_user(db)
    owner_id = user.id
    assert owner_id is not None
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
    return crud.create_item_handler(session=db, item_handler_in=item_handler_in, owner_id=owner_id)