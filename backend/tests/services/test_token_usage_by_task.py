from __future__ import annotations

import uuid

import pytest
from sqlmodel import Session, create_engine, select

from app.services.agent import token_usage as token_usage_module
from app.services.agent.token_usage import TokenUsageRecord, TokenUsageTracker


@pytest.fixture()
def tracker(tmp_path, monkeypatch) -> TokenUsageTracker:
    engine = create_engine(f"sqlite:///{tmp_path / 'token_usage.db'}")
    TokenUsageRecord.__table__.create(engine, checkfirst=True)
    monkeypatch.setattr(token_usage_module, "engine", engine)
    return TokenUsageTracker()


def test_record_persists_reply_ticket_id(tracker) -> None:
    engine = token_usage_module.engine
    tracker.record(
        "item-1",
        "model-a",
        10,
        5,
        15,
        reply_ticket_id="ticket-abc",
    )
    with Session(engine) as session:
        rows = session.exec(select(TokenUsageRecord)).all()
    assert len(rows) == 1
    assert rows[0].reply_ticket_id == "ticket-abc"
    assert rows[0].total_tokens == 15


def test_record_defaults_to_empty_ticket_id(tracker) -> None:
    tracker.record("item-1", "model-a", 1, 1, 2)
    with Session(token_usage_module.engine) as session:
        rows = session.exec(select(TokenUsageRecord)).all()
    assert rows[0].reply_ticket_id == ""


def test_get_task_stats_aggregates_by_ticket(tracker) -> None:
    item_id = str(uuid.uuid4())
    tracker.record(item_id, "model-a", 10, 5, 15, reply_ticket_id="ticket-1")
    tracker.record(item_id, "model-a", 20, 10, 30, reply_ticket_id="ticket-1")
    tracker.record(item_id, "model-a", 7, 3, 10, reply_ticket_id="ticket-2")
    # Records without a ticket and records of other items are excluded.
    tracker.record(item_id, "model-a", 100, 100, 200)
    tracker.record(str(uuid.uuid4()), "model-a", 1, 1, 2, reply_ticket_id="ticket-9")

    tasks = tracker.get_task_stats(item_id)
    assert len(tasks) == 2
    by_ticket = {row["reply_ticket_id"]: row for row in tasks}

    ticket_1 = by_ticket["ticket-1"]
    assert ticket_1["prompt_tokens"] == 30
    assert ticket_1["completion_tokens"] == 15
    assert ticket_1["total_tokens"] == 45
    assert ticket_1["turns"] == 2
    assert ticket_1["first_seen"] <= ticket_1["last_seen"]

    ticket_2 = by_ticket["ticket-2"]
    assert ticket_2["total_tokens"] == 10
    assert ticket_2["turns"] == 1
