from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlmodel import Session

from app.core.config import settings
from app.plugins.robot import service as robot_service_module
from app.plugins.robot.contracts import RobotReplyTarget
from app.services.agent import reply_ticket as reply_ticket_module
from app.services.agent import state_store, task_watchdog
from app.services.agent.reply_ticket import reply_ticket_manager
from tests.utils.item import create_random_item
from tests.utils.robot import create_random_robot


@pytest.fixture(autouse=True)
def isolated_state_store(tmp_path, monkeypatch):
    monkeypatch.setattr(
        settings,
        "AGENT_STATE_STORE_PATH",
        str(tmp_path / "agent_state.db"),
    )
    # Keep watchdog passes hermetic: never touch the real vector store.
    monkeypatch.setattr(
        task_watchdog,
        "_dedupe_memory_clusters",
        lambda now, stats: None,
    )
    state_store.reset_state_store_engine()
    reply_ticket_manager.reset()
    yield
    reply_ticket_manager.reset()
    state_store.reset_state_store_engine()


def _make_agent():
    return SimpleNamespace(_context=None)


def test_ticket_persists_and_restores_with_aliases() -> None:
    agent = _make_agent()
    ticket = reply_ticket_manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="装一下 java",
    )
    reply_ticket_manager.mark_task_plan(ticket.ticket_id, "plan-1")
    second = reply_ticket_manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="继续",
    )
    with reply_ticket_manager._lock:
        reply_ticket_manager._ticket_aliases[ticket.ticket_id] = second.ticket_id
        reply_ticket_module._persist_aliases(reply_ticket_manager._ticket_aliases)
    assert state_store.load_tickets(), "ticket rows should be persisted"

    # Simulate process death: in-memory state is gone, the store survives.
    reply_ticket_manager._tickets.clear()
    reply_ticket_manager._ticket_aliases.clear()
    assert reply_ticket_manager.get(second.ticket_id) is None

    restored = reply_ticket_module.restore_tickets_from_store()
    assert restored >= 1
    revived = reply_ticket_manager.get(second.ticket_id)
    assert revived is not None
    assert reply_ticket_manager._tickets[ticket.ticket_id].task_request_id == "plan-1"
    assert reply_ticket_manager.resolve_ticket_id(ticket.ticket_id) == second.ticket_id


def _make_dispatch_job() -> robot_service_module.QueuedRobotChatJob:
    return robot_service_module.QueuedRobotChatJob(
        robot_id=uuid.uuid4(),
        robot_owner_id=uuid.uuid4(),
        item_id=uuid.uuid4(),
        route_key="group:g1",
        message="[Current QQ message]\n装java",
        sender_key="onebot_v11:group:g1:u1",
        reply_target=RobotReplyTarget(
            target_type="group",
            target_id="g1",
            metadata={},
        ),
        conversation_key="group:g1",
        enqueued_at=datetime.now(timezone.utc),
        direct_reply_trigger=True,
        message_text="装java",
        trigger_reason="mentioned",
    )


def test_dispatch_queue_is_memory_only(monkeypatch) -> None:
    service = robot_service_module.RobotService()
    monkeypatch.setattr(service, "_ensure_dispatch_workers", lambda: None)
    assert service._enqueue_chat_job(_make_dispatch_job()) is True
    assert service._dispatch_queue.qsize() == 1
    # A "restarted" service starts empty: dispatch jobs are intentionally
    # not persisted or restored, so a restart never replays stale jobs.
    fresh = robot_service_module.RobotService()
    assert fresh._dispatch_queue.qsize() == 0


def test_chat_job_times_out_and_reports(db: Session, monkeypatch) -> None:
    item = create_random_item(db)
    robot = create_random_robot(db)
    monkeypatch.setattr(settings, "ROBOT_BACKEND_JOB_TIMEOUT_SECONDS", 0.2)

    service = robot_service_module.RobotService()

    async def slow_chat(**_kwargs):
        await asyncio.sleep(5)

    monkeypatch.setattr(service, "_chat_with_item", slow_chat)
    monkeypatch.setattr(service, "_prepare_queued_chat_message", lambda **_kwargs: "msg")
    monkeypatch.setattr(
        service,
        "conversation_controller_allows_reply",
        lambda *args, **kwargs: True,
    )
    errors: list[str] = []
    monkeypatch.setattr(
        service,
        "_record_and_send_job_error",
        lambda _job, message, **_kwargs: errors.append(message),
    )

    job = robot_service_module.QueuedRobotChatJob(
        robot_id=robot.id,
        robot_owner_id=robot.owner_id,
        item_id=item.id,
        route_key="group:g1",
        message="[Current QQ message]\n装java",
        sender_key="onebot_v11:group:g1:u1",
        reply_target=RobotReplyTarget(
            target_type="group",
            target_id="g1",
            metadata={},
        ),
        conversation_key="group:g1",
        enqueued_at=datetime.now(timezone.utc),
        direct_reply_trigger=True,
        message_text="装java",
    )
    service._process_chat_job(job)
    assert errors and "超时" in errors[0]


def test_watchdog_removes_stale_inactive_ticket() -> None:
    agent = _make_agent()
    ticket = reply_ticket_manager.create_for_agent(
        agent,
        item_id="item-1",
        handler_id="handler-1",
        message="随便聊聊",
    )
    stored = reply_ticket_manager.get(ticket.ticket_id)
    assert stored is not None
    stored.updated_at = datetime.now() - timedelta(hours=7)

    stats = task_watchdog.run_once()
    assert stats["orphan_tickets_removed"] == 1
    assert reply_ticket_manager.get(ticket.ticket_id) is None
    assert state_store.load_tickets() == []


def test_deliver_sends_qq_ticket_via_bridge(monkeypatch) -> None:
    from app.plugins.robot.bridge_client import robot_bridge_client
    from app.plugins.robot.conversation_memory import robot_conversation_memory
    from app.services.agent.reply_ticket import ReplyTicket, reply_ticket_manager

    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        robot_bridge_client,
        "send_message",
        lambda robot_id, target, text: sent.append(
            (robot_id, target.target_id, text)
        ),
    )
    monkeypatch.setattr(
        robot_conversation_memory,
        "append_assistant_message",
        lambda *args, **kwargs: None,
    )
    ticket = ReplyTicket(
        ticket_id="t-qq-1",
        item_id="item-1",
        handler_id="handler-1",
        source_type="qq",
        source_label="QQ group:g1",
        robot_id="robot-1",
        conversation_key="group:g1",
        reply_target={"target_type": "group", "target_id": "g1", "metadata": {}},
    )
    with reply_ticket_manager._lock:
        reply_ticket_manager._tickets[ticket.ticket_id] = ticket

    assert reply_ticket_manager.deliver(ticket.ticket_id, "装好了") is True
    assert sent == [("robot-1", "g1", "装好了")]
    assert reply_ticket_manager.get(ticket.ticket_id).status == "delivered"
