"""Persistent token usage tracker backed by the app database.

Usage is keyed by ItemHandler id: one handler's items share the same cost
pool."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlmodel import Session, SQLModel, Field, col, select, func

from app.core.db import engine

logger = logging.getLogger(__name__)


class TokenUsageRecord(SQLModel, table=True):
    __tablename__ = "token_usage_record"

    id: int | None = Field(default=None, primary_key=True)
    handler_id: str = Field(index=True)
    model: str = Field(index=True)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    reply_ticket_id: str = Field(default="", index=True)
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


def init_token_usage_table() -> None:
    from sqlalchemy import inspect
    from sqlalchemy.exc import NoSuchTableError

    with engine.begin() as conn:
        try:
            columns = {
                column["name"]
                for column in inspect(conn).get_columns("token_usage_record")
            }
        except NoSuchTableError:
            columns = set()
        if columns and "handler_id" not in columns:
            # Legacy item-keyed table: usage stats are ephemeral, recreate.
            TokenUsageRecord.__table__.drop(conn)
            columns = set()
        if not columns:
            TokenUsageRecord.__table__.create(conn)
        elif "reply_ticket_id" not in columns:
            # Lightweight migration: the table predates the reply_ticket_id column.
            conn.exec_driver_sql(
                "ALTER TABLE token_usage_record "
                "ADD COLUMN reply_ticket_id VARCHAR NOT NULL DEFAULT ''"
            )


class TokenUsageTracker:
    def record(
        self,
        handler_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        reply_ticket_id: str = "",
    ) -> None:
        try:
            with Session(engine) as session:
                record = TokenUsageRecord(
                    handler_id=handler_id,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                    reply_ticket_id=str(reply_ticket_id or ""),
                )
                session.add(record)
                session.commit()
        except Exception as exc:
            logger.warning("[TokenUsage] Failed to record: %s", exc)

    def get_handler_stats(self, handler_id: str) -> dict[str, Any]:
        try:
            with Session(engine) as session:
                rows = session.exec(
                    select(
                        TokenUsageRecord.model,
                        func.sum(TokenUsageRecord.prompt_tokens).label("prompt_tokens"),
                        func.sum(TokenUsageRecord.completion_tokens).label("completion_tokens"),
                        func.sum(TokenUsageRecord.total_tokens).label("total_tokens"),
                        func.count().label("turns"),
                    )
                    .where(TokenUsageRecord.handler_id == handler_id)
                    .group_by(TokenUsageRecord.model)
                    .order_by(func.sum(TokenUsageRecord.total_tokens).desc())
                ).all()

                models = []
                total_prompt = 0
                total_completion = 0
                total_all = 0
                total_turns = 0
                for row in rows:
                    models.append({
                        "model": row[0],
                        "prompt_tokens": row[1] or 0,
                        "completion_tokens": row[2] or 0,
                        "total_tokens": row[3] or 0,
                        "turns": row[4] or 0,
                    })
                    total_prompt += row[1] or 0
                    total_completion += row[2] or 0
                    total_all += row[3] or 0
                    total_turns += row[4] or 0

                first_last = session.exec(
                    select(
                        func.min(TokenUsageRecord.created_at),
                        func.max(TokenUsageRecord.created_at),
                    ).where(TokenUsageRecord.handler_id == handler_id)
                ).one()

                return {
                    "handler_id": handler_id,
                    "total_prompt_tokens": total_prompt,
                    "total_completion_tokens": total_completion,
                    "total_tokens": total_all,
                    "total_turns": total_turns,
                    "first_seen": first_last[0] or "",
                    "last_seen": first_last[1] or "",
                    "models": models,
                }
        except Exception as exc:
            logger.warning("[TokenUsage] Failed to query: %s", exc)
            return {
                "handler_id": handler_id,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "total_tokens": 0,
                "total_turns": 0,
                "first_seen": "",
                "last_seen": "",
                "models": [],
            }


    def get_task_stats(self, handler_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Aggregate token usage per reply ticket for one handler.

        Only records with a non-empty reply_ticket_id are grouped; the caller
        enriches the rows with in-memory ticket metadata."""
        try:
            with Session(engine) as session:
                rows = session.exec(
                    select(
                        TokenUsageRecord.reply_ticket_id,
                        func.sum(TokenUsageRecord.prompt_tokens).label("prompt_tokens"),
                        func.sum(TokenUsageRecord.completion_tokens).label("completion_tokens"),
                        func.sum(TokenUsageRecord.total_tokens).label("total_tokens"),
                        func.count().label("turns"),
                        func.min(TokenUsageRecord.created_at).label("first_seen"),
                        func.max(TokenUsageRecord.created_at).label("last_seen"),
                    )
                    .where(TokenUsageRecord.handler_id == handler_id)
                    .where(TokenUsageRecord.reply_ticket_id != "")
                    .group_by(TokenUsageRecord.reply_ticket_id)
                    .order_by(func.max(TokenUsageRecord.created_at).desc())
                    .limit(limit)
                ).all()
                return [
                    {
                        "reply_ticket_id": row[0],
                        "prompt_tokens": row[1] or 0,
                        "completion_tokens": row[2] or 0,
                        "total_tokens": row[3] or 0,
                        "turns": row[4] or 0,
                        "first_seen": row[5] or "",
                        "last_seen": row[6] or "",
                    }
                    for row in rows
                ]
        except Exception as exc:
            logger.warning("[TokenUsage] Failed to query by task: %s", exc)
            return []


token_usage_tracker = TokenUsageTracker()

try:
    init_token_usage_table()
except Exception:
    pass
