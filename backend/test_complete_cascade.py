import uuid
from sqlmodel import SQLModel, create_engine, Session, select
from app.models import (
    User, Item, ItemHandler, ItemHandlerItem, ItemHandlerUser
)
from app.core.config import settings
from app.core.security import get_password_hash

# Database connection
DATABASE_URL = settings.SQLALCHEMY_DATABASE_URI
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

def test_complete_cascade():
    with Session(engine) as session:
        # Clean up any existing test data matching our test pattern
        # This is safer than deleting everything
        existing_users = session.exec(
            select(User).where(User.email == "complete_cascade_test@example.com")
        ).all()
        for user in existing_users:
            session.delete(user)
        session.commit()
        
        # Create test user
        test_user = User(
            email="complete_cascade_test@example.com",
            hashed_password=get_password_hash("password123"),
            full_name="Complete Cascade Test User",
            is_active=True
        )
        session.add(test_user)
        session.commit()
        session.refresh(test_user)
        
        user_id = test_user.id
        print(f"Created test user: {test_user.email} (ID: {user_id})")
        
        # Create items
        item1 = Item(
            title="Test Item 1",
            description="First test item",
            status="running",
            type="normal",
            owner_id=user_id
        )
        
        item2 = Item(
            title="Test Item 2",
            description="Second test item",
            status="stopped",
            type="normal",
            owner_id=user_id
        )
        
        session.add_all([item1, item2])
        session.commit()
        session.refresh(item1)
        session.refresh(item2)
        
        print(f"Created items: {item1.title} (ID: {item1.id}), {item2.title} (ID: {item2.id})")
        
        # Create item handlers
        handler1 = ItemHandler(
            name="Test Handler 1",
            model="model1",
            owner_id=user_id
        )
        
        handler2 = ItemHandler(
            name="Test Handler 2",
            model="model2",
            owner_id=user_id
        )
        
        session.add_all([handler1, handler2])
        session.commit()
        session.refresh(handler1)
        session.refresh(handler2)
        
        print(f"Created handlers: {handler1.name} (ID: {handler1.id}), {handler2.name} (ID: {handler2.id})")
        
        # Create associations
        # Link items to handlers
        association1 = ItemHandlerItem(
            item_handler_id=handler1.id,
            item_id=item1.id
        )
        
        association2 = ItemHandlerItem(
            item_handler_id=handler1.id,
            item_id=item2.id
        )
        
        association3 = ItemHandlerItem(
            item_handler_id=handler2.id,
            item_id=item1.id
        )
        
        # Link user to handlers
        user_assoc1 = ItemHandlerUser(
            item_handler_id=handler1.id,
            user_id=user_id
        )
        
        user_assoc2 = ItemHandlerUser(
            item_handler_id=handler2.id,
            user_id=user_id
        )
        
        session.add_all([association1, association2, association3, user_assoc1, user_assoc2])
        session.commit()
        
        print(f"Created {3} ItemHandlerItem associations and {2} ItemHandlerUser associations")
        
        # Count records before deletion
        def count_records():
            return {
                "users": len(session.exec(select(User)).all()),
                "items": len(session.exec(select(Item)).all()),
                "handlers": len(session.exec(select(ItemHandler)).all()),
                "handler_items": len(session.exec(select(ItemHandlerItem)).all()),
                "handler_users": len(session.exec(select(ItemHandlerUser)).all())
            }
        
        before = count_records()
        print(f"\nRecords before deletion: {before}")
        
        # Delete the user
        print(f"\nDeleting user with ID: {user_id}")
        session.delete(test_user)
        session.commit()
        
        # Count records after deletion
        after = count_records()
        print(f"\nRecords after deletion: {after}")
        
        # Verify all related records were deleted
        user_deleted = session.exec(select(User).where(User.id == user_id)).first() is None
        items_deleted = len(session.exec(select(Item).where(Item.owner_id == user_id)).all()) == 0
        handlers_deleted = len(session.exec(
            select(ItemHandler).where(
                (ItemHandler.owner_id == user_id) |
                (ItemHandler.id.in_([handler1.id, handler2.id]))
            )
        ).all()) == 0
        
        # Get all ItemHandlerItem records that were linked to our items/handlers
        remaining_handler_items = session.exec(
            select(ItemHandlerItem).where(
                (ItemHandlerItem.item_id.in_([item1.id, item2.id])) |
                (ItemHandlerItem.item_handler_id.in_([handler1.id, handler2.id]))
            )
        ).all()
        
        handler_items_deleted = len(remaining_handler_items) == 0
        
        # Get all ItemHandlerUser records that were linked to our user/handlers
        remaining_handler_users = session.exec(
            select(ItemHandlerUser).where(
                (ItemHandlerUser.user_id == user_id) |
                (ItemHandlerUser.item_handler_id.in_([handler1.id, handler2.id]))
            )
        ).all()
        
        handler_users_deleted = len(remaining_handler_users) == 0
        
        print(f"\nVerification results:")
        print(f"User deleted: {user_deleted}")
        print(f"All user's items deleted: {items_deleted}")
        print(f"All related handlers deleted: {handlers_deleted}")
        print(f"All related ItemHandlerItem records deleted: {handler_items_deleted}")
        print(f"All related ItemHandlerUser records deleted: {handler_users_deleted}")
        
        if all([user_deleted, items_deleted, handlers_deleted, handler_items_deleted, handler_users_deleted]):
            print("\n✅ SUCCESS: Complete cascade delete working correctly!")
            print("All related records were properly deleted when user was deleted.")
        else:
            print("\n❌ FAILURE: Cascade delete not working correctly!")
            
            if not handler_items_deleted:
                print(f"Remaining ItemHandlerItem records: {len(remaining_handler_items)}")
                for rec in remaining_handler_items:
                    print(f"  - item_handler_id: {rec.item_handler_id}, item_id: {rec.item_id}")
            
            if not handler_users_deleted:
                print(f"Remaining ItemHandlerUser records: {len(remaining_handler_users)}")
                for rec in remaining_handler_users:
                    print(f"  - item_handler_id: {rec.item_handler_id}, user_id: {rec.user_id}")

if __name__ == "__main__":
    test_complete_cascade()
