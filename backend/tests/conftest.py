import os
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, delete

os.environ.setdefault("TASK_WORKFLOW_PERSIST", "false")

from app.core.config import settings
from app.core.db import engine, init_db
from app.main import app
from app.models import (
    Item,
    ItemChatSession,
    ItemHandler,
    ItemHandlerItem,
    ItemHandlerUser,
    Robot,
    RobotItem,
    User,
)
from tests.utils.user import authentication_token_from_email
from tests.utils.utils import get_superuser_token_headers


@pytest.fixture(autouse=True)
def reset_plugin_marketplace_state(tmp_path, monkeypatch) -> Generator[None, None, None]:
    from app.services.agent.integrations import reload_agent_integrations
    from app.services.plugins import plugin_manager

    monkeypatch.setattr(plugin_manager, "_state_path", tmp_path / "plugin_marketplace.json")
    monkeypatch.setattr(plugin_manager, "_state_loaded", False)
    monkeypatch.setattr(plugin_manager, "_enabled_overrides", {})
    plugin_manager.reload()
    yield
    monkeypatch.setattr(plugin_manager, "_state_loaded", False)
    monkeypatch.setattr(plugin_manager, "_enabled_overrides", {})
    plugin_manager.reload()
    reload_agent_integrations(reload_plugins=False)


@pytest.fixture(scope="session", autouse=True)
def db() -> Generator[Session, None, None]:
    # Create all tables before running tests
    from sqlmodel import SQLModel
    if str(settings.SQLALCHEMY_DATABASE_URI).startswith("sqlite:///"):
        db_path = Path(str(settings.SQLALCHEMY_DATABASE_URI).replace("sqlite:///", ""))
        engine.dispose()
        if db_path.exists():
            db_path.unlink()
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        init_db(session)
        yield session
        # Clean up after tests
        session.rollback()
        statement = delete(ItemHandlerItem)
        session.execute(statement)
        statement = delete(ItemHandlerUser)
        session.execute(statement)
        statement = delete(RobotItem)
        session.execute(statement)
        statement = delete(Robot)
        session.execute(statement)
        statement = delete(ItemHandler)
        session.execute(statement)
        statement = delete(ItemChatSession)
        session.execute(statement)
        statement = delete(Item)
        session.execute(statement)
        statement = delete(User)
        session.execute(statement)
        session.commit()


@pytest.fixture(scope="module")
def client() -> Generator[TestClient, None, None]:
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="module")
def superuser_token_headers(client: TestClient) -> dict[str, str]:
    return get_superuser_token_headers(client)


@pytest.fixture(scope="module")
def normal_user_token_headers(client: TestClient, db: Session) -> dict[str, str]:
    return authentication_token_from_email(
        client=client, email=settings.EMAIL_TEST_USER, db=db
    )
