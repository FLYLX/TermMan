# Rewrite token_usage.py to use DB
code = '''"""Persistent token usage tracker backed by SQLite."""
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
    item_id: str = Field(index=True)
    model: str = Field(index=True)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    created_at: str = Field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


def init_token_usage_table() -> None:
    TokenUsageRecord.__table__.create(engine, checkfirst=True)


class TokenUsageTracker:
    def record(
        self,
        item_id: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
    ) -> None:
        try:
            with Session(engine) as session:
                record = TokenUsageRecord(
                    item_id=item_id,
                    model=model,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    total_tokens=total_tokens,
                )
                session.add(record)
                session.commit()
        except Exception as exc:
            logger.warning("[TokenUsage] Failed to record: %s", exc)

    def get_item_stats(self, item_id: str) -> dict[str, Any]:
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
                    .where(TokenUsageRecord.item_id == item_id)
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
                    ).where(TokenUsageRecord.item_id == item_id)
                ).one()

                return {
                    "item_id": item_id,
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
                "item_id": item_id,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "total_tokens": 0,
                "total_turns": 0,
                "first_seen": "",
                "last_seen": "",
                "models": [],
            }


token_usage_tracker = TokenUsageTracker()

try:
    init_token_usage_table()
except Exception:
    pass
'''

path = '/app/backend/app/services/agent/token_usage.py'
with open(path, 'w', encoding='utf-8') as f:
    f.write(code)
print("OK: rewrote token_usage.py with DB persistence")
