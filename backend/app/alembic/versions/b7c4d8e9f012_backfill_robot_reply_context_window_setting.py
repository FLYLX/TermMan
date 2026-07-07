"""Backfill robot reply context window setting

Revision ID: b7c4d8e9f012
Revises: 9e0f7d2a1c3b
Create Date: 2026-07-07 00:00:00.000000

"""

from __future__ import annotations

import json
from typing import Any

import sqlalchemy as sa
from alembic import op

revision = "b7c4d8e9f012"
down_revision = "9e0f7d2a1c3b"
branch_labels = None
depends_on = None

DEFAULT_REPLY_CONTEXT_WINDOW_SECONDS = 50
MIN_REPLY_CONTEXT_WINDOW_SECONDS = 0
MAX_REPLY_CONTEXT_WINDOW_SECONDS = 3600

robot_table = sa.table(
    "robot",
    sa.column("id"),
    sa.column("config", sa.JSON()),
)


def _coerce_config(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return {}
        if isinstance(parsed, dict):
            return dict(parsed)
    return {}


def _normalize_window_seconds(value: Any) -> int:
    try:
        parsed = int(
            value if value is not None else DEFAULT_REPLY_CONTEXT_WINDOW_SECONDS
        )
    except (TypeError, ValueError):
        parsed = DEFAULT_REPLY_CONTEXT_WINDOW_SECONDS
    return min(
        MAX_REPLY_CONTEXT_WINDOW_SECONDS,
        max(MIN_REPLY_CONTEXT_WINDOW_SECONDS, parsed),
    )


def upgrade() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.select(robot_table.c.id, robot_table.c.config)).all()
    for robot_id, raw_config in rows:
        config = _coerce_config(raw_config)
        options = config.get("options") if isinstance(config.get("options"), dict) else {}
        options = dict(options)
        normalized_window_seconds = _normalize_window_seconds(
            options.get("reply_context_window_seconds")
        )
        if options.get("reply_context_window_seconds") == normalized_window_seconds:
            continue
        options["reply_context_window_seconds"] = normalized_window_seconds
        config["options"] = options
        connection.execute(
            robot_table.update()
            .where(robot_table.c.id == robot_id)
            .values(config=config)
        )


def downgrade() -> None:
    # Keep user/application robot settings intact on downgrade.
    pass