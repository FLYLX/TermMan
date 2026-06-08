from __future__ import annotations

import secrets
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict

ROBOT_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROBOT_DIR / ".env",
        env_ignore_empty=True,
        extra="ignore",
    )

    API_V1_STR: str = "/api/v1"
    ENVIRONMENT: Literal["local", "staging", "production"] = "local"
    SECRET_KEY: str = secrets.token_urlsafe(32)

    ROBOT_BACKEND_URL: str = "http://backend:8000"
    ROBOT_BRIDGE_URL: str = "http://robot-bridge:7000"
    ROBOT_BRIDGE_SHARED_SECRET: str | None = None
    ROBOT_BRIDGE_HOST: str = "0.0.0.0"
    ROBOT_BRIDGE_PORT: int = 7000
    ROBOT_BACKEND_DISPATCH_TIMEOUT_SECONDS: float = 180.0
    ROBOT_BRIDGE_DISPATCH_QUEUE_SIZE: int = 200
    ROBOT_BRIDGE_DISPATCH_WORKERS: int = 2
    ROBOT_BRIDGE_EVENT_QUEUE_SIZE: int = 1000

    @property
    def bridge_token(self) -> str:
        return self.ROBOT_BRIDGE_SHARED_SECRET or self.SECRET_KEY


settings = Settings()
