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
        
        # Create 5 Items with daemon configuration
        # Using the same API key as the daemon for testing
        daemon_api_key = "termman_daemon_secret_key_2024"
        daemon_host = "daemon"  # 使用容器名称而不是localhost，确保Docker容器内可以正确连接
        daemon_port = 9000
        
        items = [
            Item(
                title="测试项目 1",
                description="第一个测试项目，用于演示系统功能",
                status=ItemStatus.running,
                api_key=daemon_api_key,
                socket_host=daemon_host,
                socket_port=daemon_port,
                command="python run_item.py",
                working_directory="/app/items/1",
                owner_id=superuser.id,
                input_filter_enabled=True,
                input_filter_mode="whitelist",
                input_noise_patterns=["^\\s*$", "^\\d+%$"],
                input_event_patterns={"error": ["error:", "failed:"], "warning": ["warning:"]},
                output_filter_enabled=True,
                output_filter_mode="blacklist",
                output_command_list=["rm -rf", "chmod 777", "shutdown"],
                output_sensitive_patterns=["password", "api_key", "secret"],
                output_rate_limit=10
            ),
            Item(
                title="测试项目 2",
                description="第二个测试项目，用于性能测试",
                status=ItemStatus.stopped,
                api_key=daemon_api_key,
                socket_host=daemon_host,
                socket_port=daemon_port,
                command="node server.js",
                working_directory="/app/items/2",
                owner_id=superuser.id
            ),
            Item(
                title="测试项目 3",
                description="第三个测试项目，用于数据处理",
                status=ItemStatus.error,
                api_key=daemon_api_key,
                socket_host=daemon_host,
                socket_port=daemon_port,
                command="java -jar processor.jar",
                working_directory="/app/items/3",
                owner_id=superuser.id
            ),
            Item(
                title="测试项目 4",
                description="第四个测试项目，用于API服务",
                status=ItemStatus.running,
                api_key=daemon_api_key,
                socket_host=daemon_host,
                socket_port=daemon_port,
                command="python api_server.py",
                working_directory="/app/items/4",
                owner_id=superuser.id
            ),
            Item(
                title="测试项目 5",
                description="第五个测试项目，用于定时任务",
                status=ItemStatus.starting,
                api_key=daemon_api_key,
                socket_host=daemon_host,
                socket_port=daemon_port,
                command="python cron_job.py",
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
