from __future__ import annotations

import secrets
import threading
from dataclasses import dataclass

from app.plugins.robot.contracts import RobotReplyTarget


@dataclass(frozen=True)
class RobotMCPContext:
    robot_id: str
    sender_key: str
    reply_target: RobotReplyTarget


_lock = threading.RLock()
_contexts: dict[str, RobotMCPContext] = {}


def register_robot_mcp_context(context: RobotMCPContext) -> str:
    token = secrets.token_urlsafe(32)
    with _lock:
        _contexts[token] = context
    return token


def get_robot_mcp_context(token: str) -> RobotMCPContext | None:
    if not token:
        return None
    with _lock:
        return _contexts.get(token)


def unregister_robot_mcp_context(token: str) -> None:
    if not token:
        return
    with _lock:
        _contexts.pop(token, None)
