"""Explicit QQ multi-target delivery backfill.

When a web chat user message explicitly lists two or more QQ targets
(numeric group / private ids) and the agent turn did not deliver to all of
them, this module sends the turn's final reply text to the missing targets
as a safety net. Extraction here is pure parameter extraction from explicit
numeric ids, not intent classification.
"""

from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from app.plugins.robot.contracts import RobotReplyTarget

logger = logging.getLogger(__name__)

EXPLICIT_TARGET_RE = re.compile(
    r"(私聊|私|群组|群|group|private)\s*(?:聊|组)?\s*[:：]?\s*(\d{5,12})",
    re.IGNORECASE,
)
MIN_BACKFILL_TARGET_COUNT = 2

_TARGET_TYPE_MAP = {
    "私聊": "private",
    "私": "private",
    "private": "private",
    "群组": "group",
    "群": "group",
    "group": "group",
}

_QUOTED_TEXT_RE = re.compile(r"[「\"“‘']([^」”\"’']{1,500})[」\"”’']")


def extract_explicit_qq_targets(message: str) -> list[tuple[str, str]]:
    """Extract explicit (target_type, target_id) pairs from a user message.

    Only returns targets written as a type keyword followed by a 5-12 digit
    numeric id, deduplicated in first-seen order. Plain numbers without a
    type keyword are never matched.
    """
    targets: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for match in EXPLICIT_TARGET_RE.finditer(str(message or "")):
        target_type = _TARGET_TYPE_MAP.get(match.group(1).lower())
        target_id = match.group(2)
        if not target_type or not target_id:
            continue
        key = (target_type, target_id)
        if key in seen:
            continue
        seen.add(key)
        targets.append(key)
    return targets


def _extract_quoted_text(message: str) -> str:
    match = _QUOTED_TEXT_RE.search(str(message or ""))
    if not match:
        return ""
    return match.group(1).strip()


def _resolve_item_robot_id(item_id: str) -> str:
    """Resolve the enabled robot bound to the given item; '' when none."""
    try:
        item_uuid = uuid.UUID(str(item_id))
    except (ValueError, AttributeError, TypeError):
        return ""
    try:
        from sqlmodel import Session, select

        from app.core.db import engine
        from app.models import Robot, RobotItem

        with Session(engine) as session:
            bindings = session.exec(
                select(RobotItem).where(RobotItem.item_id == item_uuid)
            ).all()
            for binding in bindings:
                robot = session.get(Robot, binding.robot_id)
                if robot is not None and robot.is_enabled:
                    return str(robot.id)
    except Exception:
        logger.exception(
            "[RobotBackfill] Failed to resolve robot for item=%s", item_id
        )
    return ""


def run_explicit_target_backfill(
    *,
    item_id: str,
    user_message: str,
    final_text: str = "",
    delivery_key: str = "",
) -> dict[str, Any] | None:
    """Backfill undelivered explicit QQ targets after a web turn finishes.

    Returns a summary dict when a backfill was attempted, else None.
    Never raises: failures are logged and recorded as robot events.
    """
    from app.plugins.robot.mcp.server import RobotMCPServer

    targets = extract_explicit_qq_targets(user_message)
    if len(targets) < MIN_BACKFILL_TARGET_COUNT:
        return None

    key = str(delivery_key or "").strip() or f"item:{item_id}"
    delivered = RobotMCPServer.get_delivered_targets(key)
    missing = [target for target in targets if target not in delivered]
    if not missing:
        return None

    # Prefer the exact text the agent already sent to a sibling target this
    # turn; then the agent's final reply; then quoted content from the user
    # message. Without any usable text there is nothing safe to backfill.
    text = ""
    delivered_texts = RobotMCPServer.get_delivered_texts(key)
    for target in targets:
        candidate = str(delivered_texts.get(target) or "").strip()
        if candidate:
            text = candidate
            break
    if not text:
        text = str(final_text or "").strip()
    if not text:
        text = _extract_quoted_text(user_message)
    if not text:
        logger.info(
            "[RobotBackfill] Skip backfill for item=%s: no usable text; targets=%s",
            item_id,
            targets,
        )
        return None

    robot_id = _resolve_item_robot_id(item_id)
    if not robot_id:
        logger.info(
            "[RobotBackfill] Skip backfill for item=%s: no enabled robot bound; "
            "targets=%s",
            item_id,
            targets,
        )
        return None

    from app.plugins.robot.bridge_client import robot_bridge_client
    from app.plugins.robot.debug_log import preview_text, record_robot_event

    backfilled: list[str] = []
    errors: list[str] = []
    for target_type, target_id in missing:
        label = f"{target_type}:{target_id}"
        target = RobotReplyTarget(
            target_type=target_type,
            target_id=target_id,
            metadata={"manual_target": True},
        )
        try:
            robot_bridge_client.send_message(robot_id, target, text)
            RobotMCPServer.mark_target_delivered(key, target_type, target_id, text)
            backfilled.append(label)
        except Exception as exc:
            logger.error(
                "[RobotBackfill] Failed to backfill %s for item=%s: %s",
                label,
                item_id,
                exc,
            )
            errors.append(f"{label}: {exc}")

    summary = {
        "robot_id": robot_id,
        "item_id": str(item_id),
        "delivery_key": key,
        "targets": [f"{target_type}:{target_id}" for target_type, target_id in targets],
        "delivered": [
            f"{target_type}:{target_id}" for target_type, target_id in sorted(delivered)
        ],
        "missing": [f"{target_type}:{target_id}" for target_type, target_id in missing],
        "backfilled": backfilled,
        "errors": errors,
    }
    logger.info(
        "[RobotBackfill] explicit_target_backfill item=%s backfilled=%s errors=%s",
        item_id,
        backfilled,
        errors,
    )
    record_robot_event(
        robot_id,
        direction="backend_to_bridge",
        event="explicit_target_backfill",
        status="error" if errors else "ok",
        message=preview_text(text),
        payload=summary,
    )
    return summary
