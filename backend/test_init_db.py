import os
import sys
import uuid
from sqlmodel import SQLModel, create_engine, Session, select
from app.models import (
    User, Item, ItemHandler, ItemHandlerItem, ItemHandlerUser,
    ItemStatus
)
from app.core.security import get_password_hash

# Add the parent directory to path to ensure correct import
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Set environment variable to ensure .env file is found
os.environ["PYTHONPATH"] = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from app.core.config import settings

# Database connection
DATABASE_URL = settings.SQLALCHEMY_DATABASE_URI

# Create engine
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

def init_db():
    # Create all tables
    SQLModel.metadata.create_all(engine)
    
    with Session(engine) as session:
        # Check if users already exist
        existing_superuser = session.exec(
            select(User).where(User.email == "2537134688@qq.com")
        ).first()
        
        existing_regular = session.exec(
            select(User).where(User.email == "12345678@qq.com")
        ).first()
        
        if existing_superuser and existing_regular:
            print("Both users already exist. Skipping initialization.")
            return
        
        if existing_superuser:
            print("Superuser already exists. Will create only regular user.")
        
        if existing_regular:
            print("Regular user already exists. Will create only superuser.")
        
        # Create superuser if not exists
        if not existing_superuser:
            test_user = User(
                email="2537134688@qq.com",
                hashed_password=get_password_hash("lx233666"),
                full_name="Test User (Superuser)",
                is_active=True,
                is_superuser=True
            )
            session.add(test_user)
            session.commit()
            session.refresh(test_user)
            
            print(f"Created user: {test_user.email} (Superuser) with id: {test_user.id}")
            
            # Create items for the superuser
            superuser_items = [
                Item(
                    title="测试项目 1",
                    description="第一个测试项目",
                    status=ItemStatus.running,

                    config={"key1": "value1", "key2": "value2"},
                    resource_usage={"cpu": "10%", "memory": "200MB"},
                    log_path="/logs/test1.log",
                    owner_id=test_user.id
                ),
                Item(
                    title="测试项目 2",
                    description="第二个测试项目",
                    status=ItemStatus.stopped,

                    config={"setting1": "option1"},
                    resource_usage={"cpu": "5%", "memory": "100MB"},
                    log_path="/logs/test2.log",
                    owner_id=test_user.id
                ),
                Item(
                    title="测试项目 3",
                    description="第三个测试项目",
                    status=ItemStatus.error,
                    config={"param1": "data1"},
                    resource_usage={"cpu": "15%", "memory": "300MB"},
                    log_path="/logs/test3.log",
                    owner_id=test_user.id
                )
            ]
            
            session.add_all(superuser_items)
            session.commit()
            
            for item in superuser_items:
                session.refresh(item)
                print(f"Created item: {item.title} with id: {item.id}")
            
            # Create item handlers for superuser
            superuser_handlers = [
                ItemHandler(
                    name="测试处理器 1",
                    model="gpt-3.5-turbo",
                    api_key="test_key_123",
                    api_url="https://api.example.com/v1",
                    owner_id=test_user.id
                ),
                ItemHandler(
                    name="测试处理器 2",
                    model=None,  # Optional field
                    api_key="test_key_456",
                    api_url="https://api.example.com/v2",
                    owner_id=test_user.id
                )
            ]
            
            session.add_all(superuser_handlers)
            session.commit()
            
            for handler in superuser_handlers:
                session.refresh(handler)
                print(f"Created handler: {handler.name} with id: {handler.id}")
            
            # Create relationships between handlers and items for superuser
            superuser_handler_item_relationships = [
                ItemHandlerItem(item_handler_id=superuser_handlers[0].id, item_id=superuser_items[0].id),
                ItemHandlerItem(item_handler_id=superuser_handlers[0].id, item_id=superuser_items[1].id),
                ItemHandlerItem(item_handler_id=superuser_handlers[1].id, item_id=superuser_items[2].id)
            ]
            
            session.add_all(superuser_handler_item_relationships)
            session.commit()
            
            print(f"Created {len(superuser_handler_item_relationships)} handler-item relationships for superuser")
            
            # Create relationships between handlers and users for superuser
            superuser_handler_user_relationships = [
                ItemHandlerUser(item_handler_id=superuser_handlers[0].id, user_id=test_user.id),
                ItemHandlerUser(item_handler_id=superuser_handlers[1].id, user_id=test_user.id)
            ]
            
            session.add_all(superuser_handler_user_relationships)
            session.commit()
            
            print(f"Created {len(superuser_handler_user_relationships)} handler-user relationships for superuser")
        else:
            # Get existing superuser
            test_user = existing_superuser
            # Get existing superuser handlers for cross-user relationships
            superuser_handlers = session.exec(
                select(ItemHandler).where(ItemHandler.owner_id == test_user.id)
            ).all()
            
            if not superuser_handlers:
                superuser_handlers = []
        
        # Create regular user if not exists
        if not existing_regular:
            regular_user = User(
                email="12345678@qq.com",
                hashed_password=get_password_hash("lx233666"),
                full_name="Regular User",
                is_active=True,
                is_superuser=False
            )
            session.add(regular_user)
            session.commit()
            session.refresh(regular_user)
            
            print(f"\nCreated user: {regular_user.email} (Regular User) with id: {regular_user.id}")
            
            # Create items for the regular user
            regular_items = [
                Item(
                    title="普通用户项目 1",
                    description="普通用户的第一个项目",
                    status=ItemStatus.running,
                    
                    config={"service": "web", "port": 8080},
                    resource_usage={"cpu": "5%", "memory": "150MB"},
                    log_path="/logs/regular1.log",
                    owner_id=regular_user.id
                ),
                Item(
                    title="普通用户项目 2",
                    description="普通用户的第二个项目",
                    status=ItemStatus.stopped,
                    
                    config={"service": "database", "type": "postgres"},
                    resource_usage={"cpu": "8%", "memory": "300MB"},
                    log_path="/logs/regular2.log",
                    owner_id=regular_user.id
                ),
                Item(
                    title="普通用户项目 3",
                    description="普通用户的第三个项目",
                    status=ItemStatus.starting,
                    
                    config={"service": "cache", "ttl": 3600},
                    resource_usage={"cpu": "3%", "memory": "80MB"},
                    log_path="/logs/regular3.log",
                    owner_id=regular_user.id
                )
            ]
            
            session.add_all(regular_items)
            session.commit()
            
            for item in regular_items:
                session.refresh(item)
                print(f"Created item: {item.title} with id: {item.id}")
            
            # Create item handlers for regular user
            regular_handlers = [
                ItemHandler(
                    name="普通用户处理器 1",
                    model="gpt-4",
                    api_key="regular_key_001",
                    api_url="https://api.example.com/regular/v1",
                    owner_id=regular_user.id
                ),
                ItemHandler(
                    name="普通用户处理器 2",
                    model="claude-3",
                    api_key="regular_key_002",
                    api_url="https://api.example.com/regular/v2",
                    owner_id=regular_user.id
                )
            ]
            
            session.add_all(regular_handlers)
            session.commit()
            
            for handler in regular_handlers:
                session.refresh(handler)
                print(f"Created handler: {handler.name} with id: {handler.id}")
            
            # Create relationships between handlers and items for regular user
            regular_handler_item_relationships = [
                ItemHandlerItem(item_handler_id=regular_handlers[0].id, item_id=regular_items[0].id),
                ItemHandlerItem(item_handler_id=regular_handlers[0].id, item_id=regular_items[1].id),
                ItemHandlerItem(item_handler_id=regular_handlers[1].id, item_id=regular_items[2].id)
            ]
            
            session.add_all(regular_handler_item_relationships)
            session.commit()
            
            print(f"Created {len(regular_handler_item_relationships)} handler-item relationships for regular user")
            
            # Create relationships between handlers and users for regular user
            regular_handler_user_relationships = [
                ItemHandlerUser(item_handler_id=regular_handlers[0].id, user_id=regular_user.id),
                ItemHandlerUser(item_handler_id=regular_handlers[1].id, user_id=regular_user.id)
            ]
            
            session.add_all(regular_handler_user_relationships)
            session.commit()
            
            print(f"Created {len(regular_handler_user_relationships)} handler-user relationships for regular user")
            
            # Also allow superuser to access regular user's handlers if both users exist
            if not existing_superuser or (existing_superuser and superuser_handlers):
                cross_relationships = []
                
                # Superuser can access regular user's first handler
                cross_relationships.append(
                    ItemHandlerUser(item_handler_id=regular_handlers[0].id, user_id=test_user.id)
                )
                
                # Regular user can access superuser's first handler if available
                if superuser_handlers:
                    cross_relationships.append(
                        ItemHandlerUser(item_handler_id=superuser_handlers[0].id, user_id=regular_user.id)
                    )
                
                if cross_relationships:
                    session.add_all(cross_relationships)
                    session.commit()
                    print(f"Created {len(cross_relationships)} cross-user handler relationships")
        else:
            print("\nRegular user already exists. Skipping creation.")
        
        # Verify all records were created correctly
        print("\nVerifying database contents:")
        
        # Count users
        user_count = session.exec(select(User)).all()
        print(f"Total users: {len(user_count)}")
        
        # Count items
        item_count = session.exec(select(Item)).all()
        print(f"Total items: {len(item_count)}")
        
        # Count handlers
        handler_count = session.exec(select(ItemHandler)).all()
        print(f"Total handlers: {len(handler_count)}")
        
        # Count handler-item relationships
        h_item_count = session.exec(select(ItemHandlerItem)).all()
        print(f"Total handler-item relationships: {len(h_item_count)}")
        
        # Count handler-user relationships
        h_user_count = session.exec(select(ItemHandlerUser)).all()
        print(f"Total handler-user relationships: {len(h_user_count)}")
        
        print("\nDatabase initialization completed successfully!")

if __name__ == "__main__":
    init_db()
