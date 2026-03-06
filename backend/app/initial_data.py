import logging
import uuid

from sqlmodel import Session, SQLModel

from app.core.db import engine, init_db
from app.models import User, Item, ItemHandler, ItemStatus
from app.core.security import get_password_hash

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_tables() -> None:
    """Create all database tables"""
    logger.info("Creating database tables")
    SQLModel.metadata.create_all(engine)
    logger.info("Database tables created")


def init() -> None:
    with Session(engine) as session:
        init_db(session)


def init_test_data() -> None:
    """Initialize test data including superuser, items, and item handlers"""
    logger.info("Initializing test data")
    
    with Session(engine) as session:
        # Check if the specified superuser already exists
        admin_email = "administer@outlook.com"
        existing_superuser = session.exec(
            session.query(User).where(User.email == admin_email)
        ).first()
        
        if existing_superuser:
            logger.info(f"Superuser {admin_email} already exists. Skipping test data initialization.")
            return
        
        # Create the superuser
        superuser = User(
            email=admin_email,
            hashed_password=get_password_hash("administer"),
            full_name="System Administrator",
            is_active=True,
            is_superuser=True
        )
        session.add(superuser)
        session.commit()
        session.refresh(superuser)
        
        logger.info(f"Created superuser: {superuser.email} with id: {superuser.id}")
        
        # Create 3 ItemHandlers
        item_handlers = [
            ItemHandler(
                name="项目处理器 1",
                model="gpt-3.5-turbo",
                api_key="handler_key_001",
                api_url="https://api.example.com/handlers/v1",
                owner_id=superuser.id
            ),
            ItemHandler(
                name="项目处理器 2",
                model="claude-3-sonnet",
                api_key="handler_key_002",
                api_url="https://api.example.com/handlers/v2",
                owner_id=superuser.id
            ),
            ItemHandler(
                name="项目处理器 3",
                model="gemini-1.5-pro",
                api_key="handler_key_003",
                api_url="https://api.example.com/handlers/v3",
                owner_id=superuser.id
            )
        ]
        
        session.add_all(item_handlers)
        session.commit()
        
        for handler in item_handlers:
            session.refresh(handler)
            logger.info(f"Created ItemHandler: {handler.name} with id: {handler.id}")
        
        # Create 5 Items
        items = [
            Item(
                title="测试项目 1",
                description="第一个测试项目，用于演示系统功能",
                status=ItemStatus.running,
                config={"key1": "value1", "key2": "value2"},
                resource_usage={"cpu": "10%", "memory": "200MB"},
                log_path="/logs/item1.log",
                api_key="item_key_001",
                command="python run_item.py",
                executable_path="/usr/bin/python3",
                working_directory="/app/items/1",
                owner_id=superuser.id
            ),
            Item(
                title="测试项目 2",
                description="第二个测试项目，用于性能测试",
                status=ItemStatus.stopped,
                config={"setting1": "option1", "threads": 4},
                resource_usage={"cpu": "5%", "memory": "100MB"},
                log_path="/logs/item2.log",
                api_key="item_key_002",
                command="node server.js",
                executable_path="/usr/bin/node",
                working_directory="/app/items/2",
                owner_id=superuser.id
            ),
            Item(
                title="测试项目 3",
                description="第三个测试项目，用于数据处理",
                status=ItemStatus.error,
                config={"param1": "data1", "batch_size": 1000},
                resource_usage={"cpu": "15%", "memory": "300MB"},
                log_path="/logs/item3.log",
                api_key="item_key_003",
                command="java -jar processor.jar",
                executable_path="/usr/bin/java",
                working_directory="/app/items/3",
                owner_id=superuser.id
            ),
            Item(
                title="测试项目 4",
                description="第四个测试项目，用于API服务",
                status=ItemStatus.running,
                config={"service": "api", "port": 8000},
                resource_usage={"cpu": "8%", "memory": "250MB"},
                log_path="/logs/item4.log",
                api_key="item_key_004",
                command="python api_server.py",
                executable_path="/usr/bin/python3",
                working_directory="/app/items/4",
                owner_id=superuser.id
            ),
            Item(
                title="测试项目 5",
                description="第五个测试项目，用于定时任务",
                status=ItemStatus.starting,
                config={"service": "cron", "schedule": "*/5 * * * *"},
                resource_usage={"cpu": "3%", "memory": "80MB"},
                log_path="/logs/item5.log",
                api_key="item_key_005",
                command="python cron_job.py",
                executable_path="/usr/bin/python3",
                working_directory="/app/items/5",
                owner_id=superuser.id
            )
        ]
        
        session.add_all(items)
        session.commit()
        
        for item in items:
            session.refresh(item)
            logger.info(f"Created Item: {item.title} with id: {item.id}")
        
        # Verify all records were created correctly
        logger.info("Verifying database contents:")
        
        # Count users
        user_count = session.exec(session.query(User)).all()
        logger.info(f"Total users: {len(user_count)}")
        
        # Count items
        item_count = session.exec(session.query(Item)).all()
        logger.info(f"Total items: {len(item_count)}")
        
        # Count handlers
        handler_count = session.exec(session.query(ItemHandler)).all()
        logger.info(f"Total handlers: {len(handler_count)}")
        
        logger.info("Test data initialization completed successfully!")


def main() -> None:
    logger.info("Starting database initialization")
    
    # Create tables first
    create_tables()
    
    # Initialize core data
    logger.info("Creating initial data")
    init()
    
    # Initialize test data
    logger.info("Creating test data")
    init_test_data()
    
    logger.info("All initial data created successfully")


if __name__ == "__main__":
    main()
