from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from app.plugins.robot.contracts import RobotReplyTarget
from app.plugins.robot.debug_log import record_robot_event
from app.plugins.robot.platforms import (
    resolve_bot_identity,
    resolve_platform_from_bot,
    send_text_with_bot,
)

logger = logging.getLogger(__name__)

DEFAULT_SEND_INTERVAL_SECONDS = 1.2
RATE_LIMIT_RETRY_DELAYS = (3.0, 8.0)


@dataclass
class _SendBucket:
    lock: asyncio.Lock
    next_at: float = 0.0


_buckets: dict[str, _SendBucket] = {}


def _target_key(target: RobotReplyTarget) -> str:
    target_data = target.metadata.get("target")
    if isinstance(target_data, dict):
        target_id = target_data.get("id") or target_data.get("parent_id") or target.target_id
        parent_id = target_data.get("parent_id") or ""
        return f"universal:{parent_id}:{target_id}"
    return f"{target.target_type}:{target.target_id}"


def _send_key(bot: Any, target: RobotReplyTarget) -> str:
    try:
        bot_identity = resolve_bot_identity(bot)
    except Exception:
        bot_identity = str(getattr(bot, "self_id", "unknown"))
    return f"{bot_identity}:{_target_key(target)}"


def _is_platform_rate_limit(exc: Exception) -> bool:
    text = str(exc)
    return (
        "100017" in text
        or "22009" in text
        or "msg limit exceed" in text.lower()
        or "rate limit" in text.lower()
    )


def _send_interval_for_bot(bot: Any) -> float:
    platform_id = resolve_platform_from_bot(bot)
    if platform_id == "qq_official":
        return DEFAULT_SEND_INTERVAL_SECONDS
    return 0.2


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _is_reply_window_expired(target: RobotReplyTarget) -> bool:
    expires_at = _parse_timestamp(target.metadata.get("reply_expires_at"))
    if expires_at is None:
        return False
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) >= expires_at


def _consume_reply_budget(target: RobotReplyTarget) -> bool:
    if _is_reply_window_expired(target):
        return False

    max_replies = target.metadata.get("reply_max_replies")
    if max_replies is None:
        return True

    try:
        max_count = int(max_replies)
        used_count = int(target.metadata.get("reply_used_replies") or 0)
    except (TypeError, ValueError):
        return True

    if used_count >= max_count:
        return False

    target.metadata["reply_used_replies"] = used_count + 1
    return True


def _record_budget_drop(
    robot_id: str | None,
    target: RobotReplyTarget,
    text: str,
) -> None:
    if not robot_id:
        return
    record_robot_event(
        robot_id,
        direction="bridge_to_platform",
        event="platform_send_dropped",
        status="error",
        message="QQ passive reply window expired or reply budget exhausted",
        payload={
            "target_type": target.target_type,
            "target_id": target.target_id,
            "reply_max_replies": target.metadata.get("reply_max_replies"),
            "reply_used_replies": target.metadata.get("reply_used_replies"),
            "reply_expires_at": target.metadata.get("reply_expires_at"),
            "text_length": len(text),
        },
    )


async def send_text_with_rate_limit(
    bot: Any,
    target: RobotReplyTarget,
    text: str,
    *,
    robot_id: str | None = None,
) -> None:
    normalized_text = (text or "").strip()
    if not normalized_text:
        return

    if target.metadata.get("reply_platform") == "qq_official" and not _consume_reply_budget(target):
        _record_budget_drop(robot_id, target, normalized_text)
        return

    key = _send_key(bot, target)
    bucket = _buckets.setdefault(key, _SendBucket(lock=asyncio.Lock()))

    async with bucket.lock:
        now = time.monotonic()
        if bucket.next_at > now:
            await asyncio.sleep(bucket.next_at - now)

        interval = _send_interval_for_bot(bot)
        attempts = 1 + len(RATE_LIMIT_RETRY_DELAYS)
        for attempt in range(attempts):
            try:
                await send_text_with_bot(bot, target, normalized_text)
                if robot_id:
                    record_robot_event(
                        robot_id,
                        direction="bridge_to_platform",
                        event="platform_send_success",
                        message=normalized_text,
                        payload={
                            "target_type": target.target_type,
                            "target_id": target.target_id,
                            "reply_used_replies": target.metadata.get("reply_used_replies"),
                            "reply_max_replies": target.metadata.get("reply_max_replies"),
                        },
                    )
                bucket.next_at = time.monotonic() + interval
                return
            except Exception as exc:
                if not _is_platform_rate_limit(exc) or attempt >= len(RATE_LIMIT_RETRY_DELAYS):
                    if robot_id:
                        record_robot_event(
                            robot_id,
                            direction="bridge_to_platform",
                            event="platform_send_failed",
                            status="error",
                            message=str(exc),
                            payload={
                                "target_type": target.target_type,
                                "target_id": target.target_id,
                            },
                        )
                    raise

                delay = RATE_LIMIT_RETRY_DELAYS[attempt]
                bucket.next_at = time.monotonic() + delay
                if robot_id:
                    record_robot_event(
                        robot_id,
                        direction="bridge_to_platform",
                        event="platform_rate_limited",
                        status="error",
                        message=str(exc),
                        payload={
                            "retry_after_seconds": delay,
                            "target_type": target.target_type,
                            "target_id": target.target_id,
                        },
                    )
                logger.warning(
                    "[Bridge] Platform send rate limited; retrying in %.1fs: %s",
                    delay,
                    exc,
                )
                await asyncio.sleep(delay)
